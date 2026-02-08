from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, or_, update
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, require_admin_or_agent, require_org_admin
from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, ensure_session, send_message
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentRead,
    AgentUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.activity_log import record_activity
from app.services.agent_provisioning import (
    DEFAULT_HEARTBEAT_CONFIG,
    cleanup_agent,
    provision_agent,
    provision_main_agent,
)
from app.services.organizations import (
    OrganizationContext,
    get_active_membership,
    has_board_access,
    is_org_admin,
    list_accessible_board_ids,
    require_board_access,
)

router = APIRouter(prefix="/agents", tags=["agents"])

OFFLINE_AFTER = timedelta(minutes=10)
AGENT_SESSION_PREFIX = "agent"


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _build_session_key(agent_name: str) -> str:
    return f"{AGENT_SESSION_PREFIX}:{_slugify(agent_name)}:main"


def _workspace_path(agent_name: str, workspace_root: str | None) -> str:
    if not workspace_root:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway workspace_root is required",
        )
    root = workspace_root.rstrip("/")
    return f"{root}/workspace-{_slugify(agent_name)}"


async def _require_board(
    session: AsyncSession,
    board_id: UUID | str | None,
    *,
    user: object | None = None,
    write: bool = False,
) -> Board:
    if not board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_id is required",
        )
    board = await session.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    if user is not None:
        await require_board_access(session, user=user, board=board, write=write)  # type: ignore[arg-type]
    return board


async def _require_gateway(
    session: AsyncSession, board: Board
) -> tuple[Gateway, GatewayClientConfig]:
    if not board.gateway_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is required",
        )
    gateway = await session.get(Gateway, board.gateway_id)
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is invalid",
        )
    if gateway.organization_id != board.organization_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is invalid",
        )
    if not gateway.main_session_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway main_session_key is required",
        )
    if not gateway.url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway url is required",
        )
    if not gateway.workspace_root:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway workspace_root is required",
        )
    return gateway, GatewayClientConfig(url=gateway.url, token=gateway.token)


def _gateway_client_config(gateway: Gateway) -> GatewayClientConfig:
    if not gateway.url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway url is required",
        )
    return GatewayClientConfig(url=gateway.url, token=gateway.token)


async def _get_gateway_main_session_keys(session: AsyncSession) -> set[str]:
    keys = (await session.exec(select(Gateway.main_session_key))).all()
    return {key for key in keys if key}


def _is_gateway_main(agent: Agent, main_session_keys: set[str]) -> bool:
    return bool(agent.openclaw_session_id and agent.openclaw_session_id in main_session_keys)


def _to_agent_read(agent: Agent, main_session_keys: set[str]) -> AgentRead:
    model = AgentRead.model_validate(agent, from_attributes=True)
    return model.model_copy(update={"is_gateway_main": _is_gateway_main(agent, main_session_keys)})


async def _find_gateway_for_main_session(
    session: AsyncSession, session_key: str | None
) -> Gateway | None:
    if not session_key:
        return None
    return (
        await session.exec(select(Gateway).where(Gateway.main_session_key == session_key))
    ).first()


async def _ensure_gateway_session(
    agent_name: str,
    config: GatewayClientConfig,
) -> tuple[str, str | None]:
    session_key = _build_session_key(agent_name)
    try:
        await ensure_session(session_key, config=config, label=agent_name)
        return session_key, None
    except OpenClawGatewayError as exc:
        return session_key, str(exc)


def _with_computed_status(agent: Agent) -> Agent:
    now = utcnow()
    if agent.status in {"deleting", "updating"}:
        return agent
    if agent.last_seen_at is None:
        agent.status = "provisioning"
    elif now - agent.last_seen_at > OFFLINE_AFTER:
        agent.status = "offline"
    return agent


def _serialize_agent(agent: Agent, main_session_keys: set[str]) -> dict[str, object]:
    return _to_agent_read(_with_computed_status(agent), main_session_keys).model_dump(mode="json")


async def _fetch_agent_events(
    session: AsyncSession,
    board_id: UUID | None,
    since: datetime,
) -> list[Agent]:
    statement = select(Agent)
    if board_id:
        statement = statement.where(col(Agent.board_id) == board_id)
    statement = statement.where(
        or_(
            col(Agent.updated_at) >= since,
            col(Agent.last_seen_at) >= since,
        )
    ).order_by(asc(col(Agent.updated_at)))
    return list(await session.exec(statement))


async def _require_user_context(session: AsyncSession, user: User | None) -> OrganizationContext:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await get_active_membership(session, user)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    organization = await session.get(Organization, member.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return OrganizationContext(organization=organization, member=member)


async def _require_agent_access(
    session: AsyncSession,
    *,
    agent: Agent,
    ctx: OrganizationContext,
    write: bool,
) -> None:
    if agent.board_id is None:
        if not is_org_admin(ctx.member):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        gateway = await _find_gateway_for_main_session(session, agent.openclaw_session_id)
        if gateway is None or gateway.organization_id != ctx.organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return

    board = await session.get(Board, agent.board_id)
    if board is None or board.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not await has_board_access(session, member=ctx.member, board=board, write=write):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _record_heartbeat(session: AsyncSession, agent: Agent) -> None:
    record_activity(
        session,
        event_type="agent.heartbeat",
        message=f"Heartbeat received from {agent.name}.",
        agent_id=agent.id,
    )


def _record_instruction_failure(
    session: AsyncSession, agent: Agent, error: str, action: str
) -> None:
    action_label = action.replace("_", " ").capitalize()
    record_activity(
        session,
        event_type=f"agent.{action}.failed",
        message=f"{action_label} message failed: {error}",
        agent_id=agent.id,
    )


async def _send_wakeup_message(
    agent: Agent, config: GatewayClientConfig, verb: str = "provisioned"
) -> None:
    session_key = agent.openclaw_session_id or _build_session_key(agent.name)
    await ensure_session(session_key, config=config, label=agent.name)
    message = (
        f"Hello {agent.name}. Your workspace has been {verb}.\n\n"
        "Start the agent, run BOOT.md, and if BOOTSTRAP.md exists run it once "
        "then delete it. Begin heartbeats after startup."
    )
    await send_message(message, session_key=session_key, config=config, deliver=True)


@router.get("", response_model=DefaultLimitOffsetPage[AgentRead])
async def list_agents(
    board_id: UUID | None = Query(default=None),
    gateway_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> DefaultLimitOffsetPage[AgentRead]:
    main_session_keys = await _get_gateway_main_session_keys(session)
    board_ids = await list_accessible_board_ids(session, member=ctx.member, write=False)
    if board_id is not None and board_id not in set(board_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not board_ids:
        statement = select(Agent).where(col(Agent.id).is_(None))
    else:
        base_filter: ColumnElement[bool] = col(Agent.board_id).in_(board_ids)
        if is_org_admin(ctx.member):
            gateway_keys = select(Gateway.main_session_key).where(
                col(Gateway.organization_id) == ctx.organization.id
            )
            base_filter = or_(base_filter, col(Agent.openclaw_session_id).in_(gateway_keys))
        statement = select(Agent).where(base_filter)
    if board_id is not None:
        statement = statement.where(col(Agent.board_id) == board_id)
    if gateway_id is not None:
        gateway = await session.get(Gateway, gateway_id)
        if gateway is None or gateway.organization_id != ctx.organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        statement = statement.join(Board, col(Agent.board_id) == col(Board.id)).where(
            col(Board.gateway_id) == gateway_id
        )
    statement = statement.order_by(col(Agent.created_at).desc())

    def _transform(items: Sequence[Any]) -> Sequence[Any]:
        agents = cast(Sequence[Agent], items)
        return [_to_agent_read(_with_computed_status(agent), main_session_keys) for agent in agents]

    return await paginate(session, statement, transformer=_transform)


@router.get("/stream")
async def stream_agents(
    request: Request,
    board_id: UUID | None = Query(default=None),
    since: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> EventSourceResponse:
    since_dt = _parse_since(since) or utcnow()
    last_seen = since_dt
    board_ids = await list_accessible_board_ids(session, member=ctx.member, write=False)
    allowed_ids = set(board_ids)
    if board_id is not None and board_id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        nonlocal last_seen
        while True:
            if await request.is_disconnected():
                break
            async with async_session_maker() as session:
                if board_id is not None:
                    agents = await _fetch_agent_events(session, board_id, last_seen)
                elif allowed_ids:
                    agents = await _fetch_agent_events(session, None, last_seen)
                    agents = [agent for agent in agents if agent.board_id in allowed_ids]
                else:
                    agents = []
                main_session_keys = (
                    await _get_gateway_main_session_keys(session) if agents else set()
                )
            for agent in agents:
                updated_at = agent.updated_at or agent.last_seen_at or utcnow()
                if updated_at > last_seen:
                    last_seen = updated_at
                payload = {"agent": _serialize_agent(agent, main_session_keys)}
                yield {"event": "agent", "data": json.dumps(payload)}
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator(), ping=15)


@router.post("", response_model=AgentRead)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> AgentRead:
    if actor.actor_type == "user":
        ctx = await _require_user_context(session, actor.user)
        if not is_org_admin(ctx.member):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if actor.actor_type == "agent":
        if not actor.agent or not actor.agent.is_board_lead:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only board leads can create agents",
            )
        if not actor.agent.board_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board lead must be assigned to a board",
            )
        if payload.board_id and payload.board_id != actor.agent.board_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board leads can only create agents in their own board",
            )
        payload = AgentCreate(**{**payload.model_dump(), "board_id": actor.agent.board_id})

    board = await _require_board(
        session,
        payload.board_id,
        user=actor.user if actor.actor_type == "user" else None,
        write=actor.actor_type == "user",
    )
    gateway, client_config = await _require_gateway(session, board)
    data = payload.model_dump()
    requested_name = (data.get("name") or "").strip()
    if requested_name:
        existing = (
            await session.exec(
                select(Agent)
                .where(Agent.board_id == board.id)
                .where(col(Agent.name).ilike(requested_name))
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An agent with this name already exists on this board.",
            )
        # Prevent OpenClaw session/workspace collisions by enforcing uniqueness within
        # the gateway workspace too (agents on other boards share the same gateway root).
        existing_gateway = (
            await session.exec(
                select(Agent)
                .join(Board, col(Agent.board_id) == col(Board.id))
                .where(col(Board.gateway_id) == gateway.id)
                .where(col(Agent.name).ilike(requested_name))
            )
        ).first()
        if existing_gateway:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An agent with this name already exists in this gateway workspace.",
            )
        desired_session_key = _build_session_key(requested_name)
        existing_session_key = (
            await session.exec(
                select(Agent)
                .join(Board, col(Agent.board_id) == col(Board.id))
                .where(col(Board.gateway_id) == gateway.id)
                .where(col(Agent.openclaw_session_id) == desired_session_key)
            )
        ).first()
        if existing_session_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This agent name would collide with an existing workspace session key. Pick a different name.",
            )
    agent = Agent.model_validate(data)
    agent.status = "provisioning"
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
    agent.provision_requested_at = utcnow()
    agent.provision_action = "provision"
    session_key, session_error = await _ensure_gateway_session(agent.name, client_config)
    agent.openclaw_session_id = session_key
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    if session_error:
        record_activity(
            session,
            event_type="agent.session.failed",
            message=f"Session sync failed for {agent.name}: {session_error}",
            agent_id=agent.id,
        )
    else:
        record_activity(
            session,
            event_type="agent.session.created",
            message=f"Session created for {agent.name}.",
            agent_id=agent.id,
        )
    await session.commit()
    try:
        await provision_agent(
            agent,
            board,
            gateway,
            raw_token,
            actor.user if actor.actor_type == "user" else None,
            action="provision",
        )
        await _send_wakeup_message(agent, client_config, verb="provisioned")
        agent.provision_confirm_token_hash = None
        agent.provision_requested_at = None
        agent.provision_action = None
        agent.updated_at = utcnow()
        session.add(agent)
        await session.commit()
        record_activity(
            session,
            event_type="agent.provision",
            message=f"Provisioned directly for {agent.name}.",
            agent_id=agent.id,
        )
        record_activity(
            session,
            event_type="agent.wakeup.sent",
            message=f"Wakeup message sent to {agent.name}.",
            agent_id=agent.id,
        )
        await session.commit()
    except OpenClawGatewayError as exc:
        _record_instruction_failure(session, agent, str(exc), "provision")
        await session.commit()
    except Exception as exc:  # pragma: no cover - unexpected provisioning errors
        _record_instruction_failure(session, agent, str(exc), "provision")
        await session.commit()
    main_session_keys = await _get_gateway_main_session_keys(session)
    return _to_agent_read(_with_computed_status(agent), main_session_keys)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> AgentRead:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _require_agent_access(session, agent=agent, ctx=ctx, write=False)
    main_session_keys = await _get_gateway_main_session_keys(session)
    return _to_agent_read(_with_computed_status(agent), main_session_keys)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> AgentRead:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _require_agent_access(session, agent=agent, ctx=ctx, write=True)
    updates = payload.model_dump(exclude_unset=True)
    make_main = updates.pop("is_gateway_main", None)
    if make_main is True and not is_org_admin(ctx.member):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if "status" in updates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="status is controlled by agent heartbeat",
        )
    if "board_id" in updates and updates["board_id"] is not None:
        new_board = await _require_board(session, updates["board_id"])
        if new_board.organization_id != ctx.organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not await has_board_access(session, member=ctx.member, board=new_board, write=True):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not updates and not force and make_main is None:
        main_session_keys = await _get_gateway_main_session_keys(session)
        return _to_agent_read(_with_computed_status(agent), main_session_keys)
    main_gateway = await _find_gateway_for_main_session(session, agent.openclaw_session_id)
    gateway_for_main: Gateway | None = None
    if make_main is True:
        board_source = updates.get("board_id") or agent.board_id
        board_for_main = await _require_board(session, board_source)
        gateway_for_main, _ = await _require_gateway(session, board_for_main)
        updates["board_id"] = None
        agent.is_board_lead = False
        agent.openclaw_session_id = gateway_for_main.main_session_key
        main_gateway = gateway_for_main
    elif make_main is False:
        agent.openclaw_session_id = None
    if make_main is not True and "board_id" in updates:
        await _require_board(session, updates["board_id"])
    for key, value in updates.items():
        setattr(agent, key, value)
    if make_main is None and main_gateway is not None:
        agent.board_id = None
        agent.is_board_lead = False
    agent.updated_at = utcnow()
    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    is_main_agent = False
    board: Board | None = None
    gateway: Gateway | None = None
    client_config: GatewayClientConfig | None = None
    if make_main is True:
        is_main_agent = True
        gateway = gateway_for_main
    elif make_main is None and agent.board_id is None and main_gateway is not None:
        is_main_agent = True
        gateway = main_gateway
    if is_main_agent:
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Main agent requires a gateway main_session_key",
            )
        if not gateway.main_session_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gateway main_session_key is required",
            )
        client_config = _gateway_client_config(gateway)
    else:
        if agent.board_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="board_id is required for non-main agents",
            )
        board = await _require_board(session, agent.board_id)
        gateway, client_config = await _require_gateway(session, board)
    session_key = agent.openclaw_session_id or _build_session_key(agent.name)
    try:
        if client_config is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gateway configuration is required",
            )
        await ensure_session(session_key, config=client_config, label=agent.name)
        if not agent.openclaw_session_id:
            agent.openclaw_session_id = session_key
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
    except OpenClawGatewayError as exc:
        _record_instruction_failure(session, agent, str(exc), "update")
        await session.commit()
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    agent.provision_requested_at = utcnow()
    agent.provision_action = "update"
    agent.status = "updating"
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    try:
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gateway configuration is required",
            )
        if is_main_agent:
            await provision_main_agent(
                agent,
                gateway,
                raw_token,
                auth.user,
                action="update",
                force_bootstrap=force,
                reset_session=True,
            )
        else:
            if board is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="board is required for non-main agent provisioning",
                )
            await provision_agent(
                agent,
                board,
                gateway,
                raw_token,
                auth.user,
                action="update",
                force_bootstrap=force,
                reset_session=True,
            )
        await _send_wakeup_message(agent, client_config, verb="updated")
        agent.provision_confirm_token_hash = None
        agent.provision_requested_at = None
        agent.provision_action = None
        agent.status = "online"
        agent.updated_at = utcnow()
        session.add(agent)
        await session.commit()
        record_activity(
            session,
            event_type="agent.update.direct",
            message=f"Updated directly for {agent.name}.",
            agent_id=agent.id,
        )
        record_activity(
            session,
            event_type="agent.wakeup.sent",
            message=f"Wakeup message sent to {agent.name}.",
            agent_id=agent.id,
        )
        await session.commit()
    except OpenClawGatewayError as exc:
        _record_instruction_failure(session, agent, str(exc), "update")
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway update failed: {exc}",
        ) from exc
    except Exception as exc:  # pragma: no cover - unexpected provisioning errors
        _record_instruction_failure(session, agent, str(exc), "update")
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error updating agent provisioning.",
        ) from exc
    main_session_keys = await _get_gateway_main_session_keys(session)
    return _to_agent_read(_with_computed_status(agent), main_session_keys)


@router.post("/{agent_id}/heartbeat", response_model=AgentRead)
async def heartbeat_agent(
    agent_id: str,
    payload: AgentHeartbeat,
    session: AsyncSession = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> AgentRead:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent" and actor.agent and actor.agent.id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if actor.actor_type == "user":
        ctx = await _require_user_context(session, actor.user)
        if not is_org_admin(ctx.member):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        await _require_agent_access(session, agent=agent, ctx=ctx, write=True)
    if payload.status:
        agent.status = payload.status
    elif agent.status == "provisioning":
        agent.status = "online"
    agent.last_seen_at = utcnow()
    agent.updated_at = utcnow()
    _record_heartbeat(session, agent)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    main_session_keys = await _get_gateway_main_session_keys(session)
    return _to_agent_read(_with_computed_status(agent), main_session_keys)


@router.post("/heartbeat", response_model=AgentRead)
async def heartbeat_or_create_agent(
    payload: AgentHeartbeatCreate,
    session: AsyncSession = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> AgentRead:
    # Agent tokens must heartbeat their authenticated agent record. Names are not unique.
    if actor.actor_type == "agent" and actor.agent:
        return await heartbeat_agent(
            agent_id=str(actor.agent.id),
            payload=AgentHeartbeat(status=payload.status),
            session=session,
            actor=actor,
        )

    statement = select(Agent).where(Agent.name == payload.name)
    if payload.board_id is not None:
        statement = statement.where(Agent.board_id == payload.board_id)
    agent = (await session.exec(statement)).first()
    if agent is None:
        if actor.actor_type == "agent":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if actor.actor_type == "user":
            ctx = await _require_user_context(session, actor.user)
            if not is_org_admin(ctx.member):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        board = await _require_board(
            session,
            payload.board_id,
            user=actor.user,
            write=True,
        )
        gateway, client_config = await _require_gateway(session, board)
        agent = Agent(
            name=payload.name,
            status="provisioning",
            board_id=board.id,
            heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
        )
        raw_token = generate_agent_token()
        agent.agent_token_hash = hash_agent_token(raw_token)
        agent.provision_requested_at = utcnow()
        agent.provision_action = "provision"
        session_key, session_error = await _ensure_gateway_session(agent.name, client_config)
        agent.openclaw_session_id = session_key
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        if session_error:
            record_activity(
                session,
                event_type="agent.session.failed",
                message=f"Session sync failed for {agent.name}: {session_error}",
                agent_id=agent.id,
            )
        else:
            record_activity(
                session,
                event_type="agent.session.created",
                message=f"Session created for {agent.name}.",
                agent_id=agent.id,
            )
        await session.commit()
        try:
            await provision_agent(agent, board, gateway, raw_token, actor.user, action="provision")
            await _send_wakeup_message(agent, client_config, verb="provisioned")
            agent.provision_confirm_token_hash = None
            agent.provision_requested_at = None
            agent.provision_action = None
            agent.updated_at = utcnow()
            session.add(agent)
            await session.commit()
            record_activity(
                session,
                event_type="agent.provision",
                message=f"Provisioned directly for {agent.name}.",
                agent_id=agent.id,
            )
            record_activity(
                session,
                event_type="agent.wakeup.sent",
                message=f"Wakeup message sent to {agent.name}.",
                agent_id=agent.id,
            )
            await session.commit()
        except OpenClawGatewayError as exc:
            _record_instruction_failure(session, agent, str(exc), "provision")
            await session.commit()
        except Exception as exc:  # pragma: no cover - unexpected provisioning errors
            _record_instruction_failure(session, agent, str(exc), "provision")
            await session.commit()
    else:
        if actor.actor_type == "user":
            ctx = await _require_user_context(session, actor.user)
            await _require_agent_access(session, agent=agent, ctx=ctx, write=True)

            if agent.agent_token_hash is None:
                raw_token = generate_agent_token()
                agent.agent_token_hash = hash_agent_token(raw_token)
                if agent.heartbeat_config is None:
                    agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
                agent.provision_requested_at = utcnow()
                agent.provision_action = "provision"
                session.add(agent)
                await session.commit()
                await session.refresh(agent)
                try:
                    board = await _require_board(
                        session,
                        str(agent.board_id) if agent.board_id else None,
                        user=actor.user,
                        write=True,
                    )
                    gateway, client_config = await _require_gateway(session, board)
                    await provision_agent(
                        agent, board, gateway, raw_token, actor.user, action="provision"
                    )
                    await _send_wakeup_message(agent, client_config, verb="provisioned")
                    agent.provision_confirm_token_hash = None
                    agent.provision_requested_at = None
                    agent.provision_action = None
                    agent.updated_at = utcnow()
                    session.add(agent)
                    await session.commit()
                    record_activity(
                        session,
                        event_type="agent.provision",
                        message=f"Provisioned directly for {agent.name}.",
                        agent_id=agent.id,
                    )
                    record_activity(
                        session,
                        event_type="agent.wakeup.sent",
                        message=f"Wakeup message sent to {agent.name}.",
                        agent_id=agent.id,
                    )
                    await session.commit()
                except OpenClawGatewayError as exc:
                    _record_instruction_failure(session, agent, str(exc), "provision")
                    await session.commit()
                except Exception as exc:  # pragma: no cover - unexpected provisioning errors
                    _record_instruction_failure(session, agent, str(exc), "provision")
                    await session.commit()
        elif actor.actor_type == "agent" and actor.agent and actor.agent.id != agent.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if not agent.openclaw_session_id:
        board = await _require_board(
            session,
            str(agent.board_id) if agent.board_id else None,
            user=actor.user if actor.actor_type == "user" else None,
            write=actor.actor_type == "user",
        )
        gateway, client_config = await _require_gateway(session, board)
        session_key, session_error = await _ensure_gateway_session(agent.name, client_config)
        agent.openclaw_session_id = session_key
        if session_error:
            record_activity(
                session,
                event_type="agent.session.failed",
                message=f"Session sync failed for {agent.name}: {session_error}",
                agent_id=agent.id,
            )
        else:
            record_activity(
                session,
                event_type="agent.session.created",
                message=f"Session created for {agent.name}.",
                agent_id=agent.id,
            )
        await session.commit()
    if payload.status:
        agent.status = payload.status
    elif agent.status == "provisioning":
        agent.status = "online"
    agent.last_seen_at = utcnow()
    agent.updated_at = utcnow()
    _record_heartbeat(session, agent)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    main_session_keys = await _get_gateway_main_session_keys(session)
    return _to_agent_read(_with_computed_status(agent), main_session_keys)


@router.delete("/{agent_id}", response_model=OkResponse)
async def delete_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OkResponse:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return OkResponse()
    await _require_agent_access(session, agent=agent, ctx=ctx, write=True)

    board = await _require_board(session, str(agent.board_id) if agent.board_id else None)
    gateway, client_config = await _require_gateway(session, board)
    try:
        workspace_path = await cleanup_agent(agent, gateway)
    except OpenClawGatewayError as exc:
        _record_instruction_failure(session, agent, str(exc), "delete")
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway cleanup failed: {exc}",
        ) from exc
    except Exception as exc:  # pragma: no cover - unexpected cleanup errors
        _record_instruction_failure(session, agent, str(exc), "delete")
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workspace cleanup failed: {exc}",
        ) from exc

    record_activity(
        session,
        event_type="agent.delete.direct",
        message=f"Deleted agent {agent.name}.",
        agent_id=None,
    )
    now = datetime.now()
    await session.execute(
        update(Task)
        .where(col(Task.assigned_agent_id) == agent.id)
        .where(col(Task.status) == "in_progress")
        .values(
            assigned_agent_id=None,
            status="inbox",
            in_progress_at=None,
            updated_at=now,
        )
    )
    await session.execute(
        update(Task)
        .where(col(Task.assigned_agent_id) == agent.id)
        .where(col(Task.status) != "in_progress")
        .values(
            assigned_agent_id=None,
            updated_at=now,
        )
    )
    await session.execute(
        update(ActivityEvent).where(col(ActivityEvent.agent_id) == agent.id).values(agent_id=None)
    )
    await session.delete(agent)
    await session.commit()

    # Always ask the main agent to confirm workspace cleanup.
    try:
        main_session = gateway.main_session_key
        if main_session and workspace_path:
            cleanup_message = (
                "Cleanup request for deleted agent.\n\n"
                f"Agent name: {agent.name}\n"
                f"Agent id: {agent.id}\n"
                f"Workspace path: {workspace_path}\n\n"
                "Actions:\n"
                "1) Remove the workspace directory.\n"
                "2) Reply NO_REPLY.\n"
            )
            await ensure_session(main_session, config=client_config, label="Main Agent")
            await send_message(
                cleanup_message,
                session_key=main_session,
                config=client_config,
                deliver=False,
            )
    except Exception:
        # Cleanup request is best-effort; deletion already completed.
        pass
    return OkResponse()
