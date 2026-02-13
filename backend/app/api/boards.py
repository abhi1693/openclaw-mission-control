"""Board CRUD and snapshot endpoints."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    get_board_for_actor_read,
    get_board_for_user_read,
    get_board_for_user_write,
    require_org_admin,
    require_org_member,
)
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.boards import BoardCreate, BoardRead, BoardUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.view_models import BoardGroupSnapshot, BoardSnapshot
from app.services.activity_log import record_activity
from app.services.board_group_snapshot import build_board_group_snapshot
from app.services.board_lifecycle import delete_board as delete_board_service
from app.services.board_snapshot import build_board_snapshot
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.organizations import OrganizationContext, board_access_filter

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/boards", tags=["boards"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)
ORG_MEMBER_DEP = Depends(require_org_member)
BOARD_USER_READ_DEP = Depends(get_board_for_user_read)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)
BOARD_ACTOR_READ_DEP = Depends(get_board_for_actor_read)
GATEWAY_ID_QUERY = Query(default=None)
BOARD_GROUP_ID_QUERY = Query(default=None)
INCLUDE_SELF_QUERY = Query(default=False)
INCLUDE_DONE_QUERY = Query(default=False)
PER_BOARD_TASK_LIMIT_QUERY = Query(default=5, ge=0, le=100)
AGENT_BOARD_ROLE_TAGS = cast("list[str | Enum]", ["agent-lead", "agent-worker"])


async def _require_gateway(
    session: AsyncSession,
    gateway_id: object,
    *,
    organization_id: UUID | None = None,
) -> Gateway:
    gateway = await crud.get_by_id(session, Gateway, gateway_id)
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="gateway_id is invalid",
        )
    if organization_id is not None and gateway.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="gateway_id is invalid",
        )
    return gateway


async def _require_gateway_for_create(
    payload: BoardCreate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Gateway:
    return await _require_gateway(
        session,
        payload.gateway_id,
        organization_id=ctx.organization.id,
    )


async def _require_board_group(
    session: AsyncSession,
    board_group_id: object,
    *,
    organization_id: UUID | None = None,
) -> BoardGroup:
    group = await crud.get_by_id(session, BoardGroup, board_group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_group_id is invalid",
        )
    if organization_id is not None and group.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_group_id is invalid",
        )
    return group


async def _require_board_group_for_create(
    payload: BoardCreate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardGroup | None:
    if payload.board_group_id is None:
        return None
    return await _require_board_group(
        session,
        payload.board_group_id,
        organization_id=ctx.organization.id,
    )


GATEWAY_CREATE_DEP = Depends(_require_gateway_for_create)
BOARD_GROUP_CREATE_DEP = Depends(_require_board_group_for_create)


async def _apply_board_update(
    *,
    payload: BoardUpdate,
    session: AsyncSession,
    board: Board,
) -> Board:
    updates = payload.model_dump(exclude_unset=True)
    if "gateway_id" in updates:
        await _require_gateway(
            session,
            updates["gateway_id"],
            organization_id=board.organization_id,
        )
    if "board_group_id" in updates and updates["board_group_id"] is not None:
        await _require_board_group(
            session,
            updates["board_group_id"],
            organization_id=board.organization_id,
        )
    crud.apply_updates(board, updates)
    if updates.get("board_type") == "goal" and (not board.objective or not board.success_metrics):
        # Validate only when explicitly switching to goal boards.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Goal boards require objective and success_metrics",
        )
    if not board.gateway_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="gateway_id is required",
        )
    board.updated_at = utcnow()
    return await crud.save(session, board)


def _board_group_change_message(
    *,
    action: Literal["join", "leave"],
    changed_board: Board,
    recipient_board: Board,
    group: BoardGroup,
) -> str:
    changed_label = "Joined Board" if action == "join" else "Left Board"
    guidance = (
        "1) Use cross-board discussion when work spans multiple boards.\n"
        "2) Check related board activity before acting on shared concerns.\n"
        "3) Explicitly coordinate ownership to avoid duplicate or conflicting work.\n"
    )
    if action == "leave":
        guidance = (
            "1) Treat cross-board coordination with the departed board as inactive.\n"
            "2) Re-check dependencies and ownership that previously spanned this board.\n"
            "3) Confirm no in-flight handoffs still rely on the prior group link.\n"
        )
    return (
        "BOARD GROUP UPDATED\n"
        f"{changed_label}: {changed_board.name}\n"
        f"{changed_label} ID: {changed_board.id}\n"
        f"Recipient Board: {recipient_board.name}\n"
        f"Recipient Board ID: {recipient_board.id}\n"
        f"Board Group: {group.name}\n"
        f"Board Group ID: {group.id}\n\n"
        "Coordination guidance:\n"
        f"{guidance}"
    )


async def _notify_agents_on_board_group_change(
    *,
    session: AsyncSession,
    board: Board,
    group: BoardGroup,
    action: Literal["join", "leave"],
) -> None:
    dispatch = GatewayDispatchService(session)
    group_boards = await Board.objects.filter_by(board_group_id=group.id).all(session)
    board_by_id = {item.id: item for item in group_boards}
    board_by_id.setdefault(board.id, board)
    board_ids = list(board_by_id.keys())
    if not board_ids:
        return
    agents = await Agent.objects.by_field_in("board_id", board_ids).all(session)
    if not agents:
        return

    config_by_board_id: dict[UUID, GatewayClientConfig] = {}
    for group_board in board_by_id.values():
        config = await dispatch.optional_gateway_config_for_board(group_board)
        if config is None:
            logger.warning(
                "board.group.%s.notify_skipped board_id=%s group_id=%s target_board_id=%s "
                "reason=no_gateway_config",
                action,
                board.id,
                group.id,
                group_board.id,
            )
            continue
        config_by_board_id[group_board.id] = config

    if not config_by_board_id:
        logger.warning(
            "board.group.%s.notify_skipped board_id=%s group_id=%s reason=no_gateway_config_any_board",
            action,
            board.id,
            group.id,
        )
        return

    message_by_board_id = {
        recipient_board_id: _board_group_change_message(
            action=action,
            changed_board=board,
            recipient_board=recipient_board,
            group=group,
        )
        for recipient_board_id, recipient_board in board_by_id.items()
    }

    notified = 0
    failed = 0
    skipped_missing_session = 0
    skipped_missing_config = 0
    skipped_missing_board = 0
    for agent in agents:
        if not agent.openclaw_session_id:
            skipped_missing_session += 1
            continue
        if agent.board_id is None:
            skipped_missing_board += 1
            continue
        config = config_by_board_id.get(agent.board_id)
        message = message_by_board_id.get(agent.board_id)
        recipient_board = board_by_id.get(agent.board_id)
        if config is None or message is None or recipient_board is None:
            skipped_missing_config += 1
            continue
        error = await dispatch.try_send_agent_message(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=message,
            deliver=False,
        )
        if error is None:
            notified += 1
            record_activity(
                session,
                event_type=f"board.group.{action}.notified",
                message=(
                    f"Board-group {action} notice sent to {agent.name} for board "
                    f"{recipient_board.name} related to {board.name} and {group.name}."
                ),
                agent_id=agent.id,
            )
        else:
            failed += 1
            record_activity(
                session,
                event_type=f"board.group.{action}.notify_failed",
                message=(
                    f"Board-group {action} notify failed for {agent.name} on board "
                    f"{recipient_board.name}: {error}"
                ),
                agent_id=agent.id,
            )

    if notified or failed:
        await session.commit()
    logger.info(
        "board.group.%s.notify_complete board_id=%s group_id=%s boards_total=%s agents_total=%s "
        "agents_notified=%s agents_failed=%s agents_skipped_no_session=%s "
        "agents_skipped_no_gateway=%s agents_skipped_no_board=%s",
        action,
        board.id,
        group.id,
        len(board_by_id),
        len(agents),
        notified,
        failed,
        skipped_missing_session,
        skipped_missing_config,
        skipped_missing_board,
    )


async def _notify_agents_on_board_group_addition(
    *,
    session: AsyncSession,
    board: Board,
    group: BoardGroup,
) -> None:
    await _notify_agents_on_board_group_change(
        session=session,
        board=board,
        group=group,
        action="join",
    )


async def _notify_agents_on_board_group_removal(
    *,
    session: AsyncSession,
    board: Board,
    group: BoardGroup,
) -> None:
    await _notify_agents_on_board_group_change(
        session=session,
        board=board,
        group=group,
        action="leave",
    )


@router.get("", response_model=DefaultLimitOffsetPage[BoardRead])
async def list_boards(
    gateway_id: UUID | None = GATEWAY_ID_QUERY,
    board_group_id: UUID | None = BOARD_GROUP_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> LimitOffsetPage[BoardRead]:
    """List boards visible to the current organization member."""
    statement = select(Board).where(board_access_filter(ctx.member, write=False))
    if gateway_id is not None:
        statement = statement.where(col(Board.gateway_id) == gateway_id)
    if board_group_id is not None:
        statement = statement.where(col(Board.board_group_id) == board_group_id)
    statement = statement.order_by(
        func.lower(col(Board.name)).asc(),
        col(Board.created_at).desc(),
    )
    return await paginate(session, statement)


@router.post("", response_model=BoardRead)
async def create_board(
    payload: BoardCreate,
    _gateway: Gateway = GATEWAY_CREATE_DEP,
    _board_group: BoardGroup | None = BOARD_GROUP_CREATE_DEP,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Board:
    """Create a board in the active organization."""
    data = payload.model_dump()
    data["organization_id"] = ctx.organization.id
    return await crud.create(session, Board, **data)


@router.get("/{board_id}", response_model=BoardRead)
def get_board(
    board: Board = BOARD_USER_READ_DEP,
) -> Board:
    """Get a board by id."""
    return board


@router.get("/{board_id}/snapshot", response_model=BoardSnapshot)
async def get_board_snapshot(
    board: Board = BOARD_ACTOR_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardSnapshot:
    """Get a board snapshot view model."""
    return await build_board_snapshot(session, board)


@router.get(
    "/{board_id}/group-snapshot",
    response_model=BoardGroupSnapshot,
    tags=AGENT_BOARD_ROLE_TAGS,
)
async def get_board_group_snapshot(
    *,
    include_self: bool = INCLUDE_SELF_QUERY,
    include_done: bool = INCLUDE_DONE_QUERY,
    per_board_task_limit: int = PER_BOARD_TASK_LIMIT_QUERY,
    board: Board = BOARD_ACTOR_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardGroupSnapshot:
    """Get a grouped snapshot across related boards.

    Returns high-signal cross-board status for dependency and overlap checks.
    """
    return await build_board_group_snapshot(
        session,
        board=board,
        include_self=include_self,
        include_done=include_done,
        per_board_task_limit=per_board_task_limit,
    )


@router.patch("/{board_id}", response_model=BoardRead)
async def update_board(
    payload: BoardUpdate,
    session: AsyncSession = SESSION_DEP,
    board: Board = BOARD_USER_WRITE_DEP,
) -> Board:
    """Update mutable board properties."""
    previous_group_id = board.board_group_id
    updated = await _apply_board_update(payload=payload, session=session, board=board)
    new_group_id = updated.board_group_id
    if previous_group_id is not None and previous_group_id != new_group_id:
        previous_group = await crud.get_by_id(session, BoardGroup, previous_group_id)
        if previous_group is not None:
            try:
                await _notify_agents_on_board_group_removal(
                    session=session,
                    board=updated,
                    group=previous_group,
                )
            except (OpenClawGatewayError, OSError, RuntimeError, ValueError):
                logger.exception(
                    "board.group.leave.notify_unexpected board_id=%s group_id=%s",
                    updated.id,
                    previous_group_id,
                )
    if new_group_id is not None and new_group_id != previous_group_id:
        board_group = await crud.get_by_id(session, BoardGroup, new_group_id)
        if board_group is not None:
            try:
                await _notify_agents_on_board_group_addition(
                    session=session,
                    board=updated,
                    group=board_group,
                )
            except (OpenClawGatewayError, OSError, RuntimeError, ValueError):
                logger.exception(
                    "board.group.join.notify_unexpected board_id=%s group_id=%s",
                    updated.id,
                    new_group_id,
                )
    return updated


@router.delete("/{board_id}", response_model=OkResponse)
async def delete_board(
    session: AsyncSession = SESSION_DEP,
    board: Board = BOARD_USER_WRITE_DEP,
) -> OkResponse:
    """Delete a board and all dependent records."""
    return await delete_board_service(session, board=board)
