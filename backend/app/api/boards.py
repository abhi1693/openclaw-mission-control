"""Board CRUD and snapshot endpoints."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

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
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import (
    OpenClawGatewayError,
    delete_session,
    ensure_session,
    send_message,
)
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_groups import BoardGroup
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.schemas.boards import BoardCreate, BoardRead, BoardUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.view_models import BoardGroupSnapshot, BoardSnapshot
from app.services.board_group_snapshot import build_board_group_snapshot
from app.services.board_snapshot import build_board_snapshot
from app.services.gateway_agents import gateway_agent_session_key
from app.services.organizations import OrganizationContext, board_access_filter

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/boards", tags=["boards"])

AGENT_SESSION_PREFIX = "agent"
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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _build_session_key(agent_name: str) -> str:
    return f"{AGENT_SESSION_PREFIX}:{_slugify(agent_name)}:main"


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


async def _board_gateway(
    session: AsyncSession,
    board: Board,
) -> tuple[Gateway | None, GatewayClientConfig | None]:
    if not board.gateway_id:
        return None, None
    config = await Gateway.objects.by_id(board.gateway_id).first(session)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is invalid",
        )
    if not config.url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway url is required",
        )
    if not config.workspace_root:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway workspace_root is required",
        )
    return config, GatewayClientConfig(url=config.url, token=config.token)


async def _cleanup_agent_on_gateway(
    agent: Agent,
    config: Gateway,
    client_config: GatewayClientConfig,
) -> None:
    if agent.openclaw_session_id:
        await delete_session(agent.openclaw_session_id, config=client_config)
    main_session = gateway_agent_session_key(config)
    workspace_root = config.workspace_root
    workspace_path = f"{workspace_root.rstrip('/')}/workspace-{_slugify(agent.name)}"
    cleanup_message = (
        "Cleanup request for deleted agent.\n\n"
        f"Agent name: {agent.name}\n"
        f"Agent id: {agent.id}\n"
        f"Session key: {agent.openclaw_session_id or _build_session_key(agent.name)}\n"
        f"Workspace path: {workspace_path}\n\n"
        "Actions:\n"
        "1) Remove the workspace directory.\n"
        "2) Delete any lingering session artifacts.\n"
        "Reply NO_REPLY."
    )
    await ensure_session(main_session, config=client_config, label="Gateway Agent")
    await send_message(
        cleanup_message,
        session_key=main_session,
        config=client_config,
        deliver=False,
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


@router.get("/{board_id}/group-snapshot", response_model=BoardGroupSnapshot)
async def get_board_group_snapshot(
    *,
    include_self: bool = INCLUDE_SELF_QUERY,
    include_done: bool = INCLUDE_DONE_QUERY,
    per_board_task_limit: int = PER_BOARD_TASK_LIMIT_QUERY,
    board: Board = BOARD_ACTOR_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardGroupSnapshot:
    """Get a grouped snapshot across related boards."""
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
    return await _apply_board_update(payload=payload, session=session, board=board)


@router.delete("/{board_id}", response_model=OkResponse)
async def delete_board(
    session: AsyncSession = SESSION_DEP,
    board: Board = BOARD_USER_WRITE_DEP,
) -> OkResponse:
    """Delete a board and all dependent records."""
    agents = await Agent.objects.filter_by(board_id=board.id).all(session)
    task_ids = list(
        await session.exec(select(Task.id).where(Task.board_id == board.id)),
    )

    config, client_config = await _board_gateway(session, board)
    if config and client_config:
        try:
            for agent in agents:
                await _cleanup_agent_on_gateway(agent, config, client_config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gateway cleanup failed: {exc}",
            ) from exc

    if task_ids:
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.task_id).in_(task_ids),
            commit=False,
        )
    await crud.delete_where(
        session,
        TaskDependency,
        col(TaskDependency.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.board_id) == board.id,
    )

    # Approvals can reference tasks and agents, so delete before both.
    await crud.delete_where(session, Approval, col(Approval.board_id) == board.id)

    await crud.delete_where(session, BoardMemory, col(BoardMemory.board_id) == board.id)
    await crud.delete_where(
        session,
        BoardOnboardingSession,
        col(BoardOnboardingSession.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.board_id) == board.id,
    )

    # Tasks reference agents and have dependent records.
    # delete tasks before agents.
    await crud.delete_where(session, Task, col(Task.board_id) == board.id)

    if agents:
        agent_ids = [agent.id for agent in agents]
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.agent_id).in_(agent_ids),
            commit=False,
        )
        await crud.delete_where(session, Agent, col(Agent.id).in_(agent_ids))
    await session.delete(board)
    await session.commit()
    return OkResponse()
