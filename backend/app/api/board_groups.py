"""Board group CRUD, snapshot, and heartbeat endpoints."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import ActorContext, require_admin_or_agent, require_org_admin, require_org_member
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.integrations.openclaw_gateway import OpenClawGatewayError
from app.models.agents import Agent
from app.models.board_group_memory import BoardGroupMemory
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.board_group_heartbeat import (
    BoardGroupHeartbeatApply,
    BoardGroupHeartbeatApplyResult,
)
from app.schemas.board_groups import BoardGroupCreate, BoardGroupRead, BoardGroupUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.view_models import BoardGroupSnapshot
from app.services.board_group_snapshot import build_group_snapshot
from app.services.openclaw import DEFAULT_HEARTBEAT_CONFIG, sync_gateway_agent_heartbeats
from app.services.organizations import (
    OrganizationContext,
    board_access_filter,
    get_member,
    is_org_admin,
    list_accessible_board_ids,
    member_all_boards_read,
    member_all_boards_write,
)

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.organization_members import OrganizationMember

router = APIRouter(prefix="/board-groups", tags=["board-groups"])
SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
ORG_ADMIN_DEP = Depends(require_org_admin)
ACTOR_DEP = Depends(require_admin_or_agent)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


async def _require_group_access(
    session: AsyncSession,
    *,
    group_id: UUID,
    member: OrganizationMember,
    write: bool,
) -> BoardGroup:
    group = await BoardGroup.objects.by_id(group_id).first(session)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if group.organization_id != member.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if write and member_all_boards_write(member):
        return group
    if not write and member_all_boards_read(member):
        return group

    board_ids = [
        board.id for board in await Board.objects.filter_by(board_group_id=group_id).all(session)
    ]
    if not board_ids:
        if is_org_admin(member):
            return group
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    allowed_ids = await list_accessible_board_ids(session, member=member, write=write)
    if not set(board_ids).intersection(set(allowed_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return group


@router.get("", response_model=DefaultLimitOffsetPage[BoardGroupRead])
async def list_board_groups(
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> LimitOffsetPage[BoardGroupRead]:
    """List board groups in the active organization."""
    if member_all_boards_read(ctx.member):
        statement = select(BoardGroup).where(
            col(BoardGroup.organization_id) == ctx.organization.id,
        )
    else:
        accessible_boards = select(Board.board_group_id).where(
            board_access_filter(ctx.member, write=False),
        )
        statement = select(BoardGroup).where(
            col(BoardGroup.organization_id) == ctx.organization.id,
            col(BoardGroup.id).in_(accessible_boards),
        )
    statement = statement.order_by(func.lower(col(BoardGroup.name)).asc())
    return await paginate(session, statement)


@router.post("", response_model=BoardGroupRead)
async def create_board_group(
    payload: BoardGroupCreate,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> BoardGroup:
    """Create a board group in the active organization."""
    data = payload.model_dump()
    if not (data.get("slug") or "").strip():
        data["slug"] = _slugify(data.get("name") or "")
    data["organization_id"] = ctx.organization.id
    return await crud.create(session, BoardGroup, **data)


@router.get("/{group_id}", response_model=BoardGroupRead)
async def get_board_group(
    group_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> BoardGroup:
    """Get a board group by id."""
    return await _require_group_access(
        session,
        group_id=group_id,
        member=ctx.member,
        write=False,
    )


@router.get("/{group_id}/snapshot", response_model=BoardGroupSnapshot)
async def get_board_group_snapshot(
    group_id: UUID,
    *,
    include_done: bool = False,
    per_board_task_limit: int = 5,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> BoardGroupSnapshot:
    """Get a snapshot across boards in a group."""
    group = await _require_group_access(
        session,
        group_id=group_id,
        member=ctx.member,
        write=False,
    )
    if per_board_task_limit < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    snapshot = await build_group_snapshot(
        session,
        group=group,
        exclude_board_id=None,
        include_done=include_done,
        per_board_task_limit=per_board_task_limit,
    )
    if not member_all_boards_read(ctx.member) and snapshot.boards:
        allowed_ids = set(
            await list_accessible_board_ids(session, member=ctx.member, write=False),
        )
        snapshot.boards = [item for item in snapshot.boards if item.board.id in allowed_ids]
    return snapshot


async def _authorize_heartbeat_actor(
    session: AsyncSession,
    *,
    group_id: UUID,
    group: BoardGroup,
    actor: ActorContext,
) -> None:
    if actor.actor_type == "user":
        if actor.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        member = await get_member(
            session,
            user_id=actor.user.id,
            organization_id=group.organization_id,
        )
        if member is None or not is_org_admin(member):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        await _require_group_access(
            session,
            group_id=group_id,
            member=member,
            write=True,
        )
        return
    agent = actor.agent
    if agent is None or agent.board_id is None or not agent.is_board_lead:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    board = await Board.objects.by_id(agent.board_id).first(session)
    if board is None or board.board_group_id != group_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def _agents_for_group_heartbeat(
    session: AsyncSession,
    *,
    group_id: UUID,
    include_board_leads: bool,
) -> tuple[dict[UUID, Board], list[Agent]]:
    boards = await Board.objects.filter_by(board_group_id=group_id).all(session)
    board_by_id = {board.id: board for board in boards}
    board_ids = list(board_by_id.keys())
    if not board_ids:
        return board_by_id, []
    agents = await Agent.objects.by_field_in("board_id", board_ids).all(session)
    if not include_board_leads:
        agents = [agent for agent in agents if not agent.is_board_lead]
    return board_by_id, agents


def _update_agent_heartbeat(
    *,
    agent: Agent,
    payload: BoardGroupHeartbeatApply,
) -> None:
    raw = agent.heartbeat_config
    heartbeat: dict[str, Any] = DEFAULT_HEARTBEAT_CONFIG.copy()
    if isinstance(raw, dict):
        heartbeat.update(raw)
    heartbeat["every"] = payload.every
    if payload.target is not None:
        heartbeat["target"] = payload.target
    elif "target" not in heartbeat:
        heartbeat["target"] = DEFAULT_HEARTBEAT_CONFIG.get("target", "none")
    agent.heartbeat_config = heartbeat
    agent.updated_at = utcnow()


async def _sync_gateway_heartbeats(
    session: AsyncSession,
    *,
    board_by_id: dict[UUID, Board],
    agents: list[Agent],
) -> list[UUID]:
    agents_by_gateway_id: dict[UUID, list[Agent]] = {}
    for agent in agents:
        board_id = agent.board_id
        if board_id is None:
            continue
        board = board_by_id.get(board_id)
        if board is None or board.gateway_id is None:
            continue
        agents_by_gateway_id.setdefault(board.gateway_id, []).append(agent)

    failed_agent_ids: list[UUID] = []
    gateway_ids = list(agents_by_gateway_id.keys())
    gateways = await Gateway.objects.by_ids(gateway_ids).all(session)
    gateway_by_id = {gateway.id: gateway for gateway in gateways}
    for gateway_id, gateway_agents in agents_by_gateway_id.items():
        gateway = gateway_by_id.get(gateway_id)
        if gateway is None or not gateway.url or not gateway.workspace_root:
            failed_agent_ids.extend([agent.id for agent in gateway_agents])
            continue
        try:
            await sync_gateway_agent_heartbeats(gateway, gateway_agents)
        except OpenClawGatewayError:
            failed_agent_ids.extend([agent.id for agent in gateway_agents])
    return failed_agent_ids


@router.post("/{group_id}/heartbeat", response_model=BoardGroupHeartbeatApplyResult)
async def apply_board_group_heartbeat(
    group_id: UUID,
    payload: BoardGroupHeartbeatApply,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardGroupHeartbeatApplyResult:
    """Apply heartbeat settings to agents in a board group."""
    group = await BoardGroup.objects.by_id(group_id).first(session)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _authorize_heartbeat_actor(
        session,
        group_id=group_id,
        group=group,
        actor=actor,
    )
    board_by_id, agents = await _agents_for_group_heartbeat(
        session,
        group_id=group_id,
        include_board_leads=payload.include_board_leads,
    )
    if not agents:
        return BoardGroupHeartbeatApplyResult(
            board_group_id=group_id,
            requested=payload.model_dump(mode="json"),
            updated_agent_ids=[],
            failed_agent_ids=[],
        )

    updated_agent_ids: list[UUID] = []
    for agent in agents:
        _update_agent_heartbeat(agent=agent, payload=payload)
        session.add(agent)
        updated_agent_ids.append(agent.id)

    await session.commit()
    failed_agent_ids = await _sync_gateway_heartbeats(
        session,
        board_by_id=board_by_id,
        agents=agents,
    )

    return BoardGroupHeartbeatApplyResult(
        board_group_id=group_id,
        requested=payload.model_dump(mode="json"),
        updated_agent_ids=updated_agent_ids,
        failed_agent_ids=failed_agent_ids,
    )


@router.patch("/{group_id}", response_model=BoardGroupRead)
async def update_board_group(
    payload: BoardGroupUpdate,
    group_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> BoardGroup:
    """Update a board group."""
    group = await _require_group_access(
        session,
        group_id=group_id,
        member=ctx.member,
        write=True,
    )
    updates = payload.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] is not None and not updates["slug"].strip():
        updates["slug"] = _slugify(updates.get("name") or group.name)
    updates["updated_at"] = utcnow()
    return await crud.patch(session, group, updates)


@router.delete("/{group_id}", response_model=OkResponse)
async def delete_board_group(
    group_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete a board group."""
    await _require_group_access(
        session,
        group_id=group_id,
        member=ctx.member,
        write=True,
    )

    # Boards reference groups, so clear the FK first to keep deletes simple.
    await crud.update_where(
        session,
        Board,
        col(Board.board_group_id) == group_id,
        board_group_id=None,
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardGroupMemory,
        col(BoardGroupMemory.board_group_id) == group_id,
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardGroup,
        col(BoardGroup.id) == group_id,
        commit=False,
    )
    await session.commit()
    return OkResponse()
