from __future__ import annotations

import re
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import ActorContext, require_admin_or_agent, require_org_admin, require_org_member
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organization_members import OrganizationMember
from app.schemas.board_group_heartbeat import (
    BoardGroupHeartbeatApply,
    BoardGroupHeartbeatApplyResult,
)
from app.schemas.board_groups import BoardGroupCreate, BoardGroupRead, BoardGroupUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.view_models import BoardGroupSnapshot
from app.services.agent_provisioning import DEFAULT_HEARTBEAT_CONFIG, sync_gateway_agent_heartbeats
from app.services.board_group_snapshot import build_group_snapshot
from app.services.organizations import (
    OrganizationContext,
    board_access_filter,
    get_member,
    is_org_admin,
    list_accessible_board_ids,
    member_all_boards_read,
    member_all_boards_write,
)

router = APIRouter(prefix="/board-groups", tags=["board-groups"])


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
    group = await session.get(BoardGroup, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if group.organization_id != member.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if write and member_all_boards_write(member):
        return group
    if not write and member_all_boards_read(member):
        return group

    board_ids = list(
        await session.exec(select(Board.id).where(col(Board.board_group_id) == group_id))
    )
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
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> DefaultLimitOffsetPage[BoardGroupRead]:
    if member_all_boards_read(ctx.member):
        statement = select(BoardGroup).where(col(BoardGroup.organization_id) == ctx.organization.id)
    else:
        accessible_boards = select(Board.board_group_id).where(
            board_access_filter(ctx.member, write=False)
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
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> BoardGroup:
    data = payload.model_dump()
    if not (data.get("slug") or "").strip():
        data["slug"] = _slugify(data.get("name") or "")
    data["organization_id"] = ctx.organization.id
    return await crud.create(session, BoardGroup, **data)


@router.get("/{group_id}", response_model=BoardGroupRead)
async def get_board_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> BoardGroup:
    return await _require_group_access(session, group_id=group_id, member=ctx.member, write=False)


@router.get("/{group_id}/snapshot", response_model=BoardGroupSnapshot)
async def get_board_group_snapshot(
    group_id: UUID,
    include_done: bool = False,
    per_board_task_limit: int = 5,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> BoardGroupSnapshot:
    group = await _require_group_access(session, group_id=group_id, member=ctx.member, write=False)
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
        allowed_ids = set(await list_accessible_board_ids(session, member=ctx.member, write=False))
        snapshot.boards = [item for item in snapshot.boards if item.board.id in allowed_ids]
    return snapshot


@router.post("/{group_id}/heartbeat", response_model=BoardGroupHeartbeatApplyResult)
async def apply_board_group_heartbeat(
    group_id: UUID,
    payload: BoardGroupHeartbeatApply,
    session: AsyncSession = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> BoardGroupHeartbeatApplyResult:
    group = await session.get(BoardGroup, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

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
    elif actor.actor_type == "agent":
        agent = actor.agent
        if agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if agent.board_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if not agent.is_board_lead:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        board = await session.get(Board, agent.board_id)
        if board is None or board.board_group_id != group_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    boards = list(await session.exec(select(Board).where(col(Board.board_group_id) == group_id)))
    board_by_id = {board.id: board for board in boards}
    board_ids = list(board_by_id.keys())
    if not board_ids:
        return BoardGroupHeartbeatApplyResult(
            board_group_id=group_id,
            requested=payload.model_dump(mode="json"),
            updated_agent_ids=[],
            failed_agent_ids=[],
        )

    agents = list(await session.exec(select(Agent).where(col(Agent.board_id).in_(board_ids))))
    if not payload.include_board_leads:
        agents = [agent for agent in agents if not agent.is_board_lead]

    updated_agent_ids: list[UUID] = []
    for agent in agents:
        raw = agent.heartbeat_config
        heartbeat: dict[str, Any] = (
            cast(dict[str, Any], dict(raw))
            if isinstance(raw, dict)
            else cast(dict[str, Any], DEFAULT_HEARTBEAT_CONFIG.copy())
        )
        heartbeat["every"] = payload.every
        if payload.target is not None:
            heartbeat["target"] = payload.target
        elif "target" not in heartbeat:
            heartbeat["target"] = DEFAULT_HEARTBEAT_CONFIG.get("target", "none")
        agent.heartbeat_config = heartbeat
        agent.updated_at = utcnow()
        session.add(agent)
        updated_agent_ids.append(agent.id)

    await session.commit()

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
    gateways = list(await session.exec(select(Gateway).where(col(Gateway.id).in_(gateway_ids))))
    gateway_by_id = {gateway.id: gateway for gateway in gateways}
    for gateway_id, gateway_agents in agents_by_gateway_id.items():
        gateway = gateway_by_id.get(gateway_id)
        if gateway is None or not gateway.url or not gateway.workspace_root:
            failed_agent_ids.extend([agent.id for agent in gateway_agents])
            continue
        try:
            await sync_gateway_agent_heartbeats(gateway, gateway_agents)
        except Exception:
            failed_agent_ids.extend([agent.id for agent in gateway_agents])

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
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> BoardGroup:
    group = await _require_group_access(session, group_id=group_id, member=ctx.member, write=True)
    updates = payload.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] is not None and not updates["slug"].strip():
        updates["slug"] = _slugify(updates.get("name") or group.name)
    for key, value in updates.items():
        setattr(group, key, value)
    group.updated_at = utcnow()
    return await crud.save(session, group)


@router.delete("/{group_id}", response_model=OkResponse)
async def delete_board_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OkResponse:
    await _require_group_access(session, group_id=group_id, member=ctx.member, write=True)

    # Boards reference groups, so clear the FK first to keep deletes simple.
    await session.execute(
        update(Board).where(col(Board.board_group_id) == group_id).values(board_group_id=None)
    )
    await session.execute(delete(BoardGroup).where(col(BoardGroup.id) == group_id))
    await session.commit()
    return OkResponse()
