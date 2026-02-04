from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select
from sqlalchemy import update

from app.api.deps import ActorContext, require_admin_auth, require_admin_or_agent
from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.auth import AuthContext
from app.db.session import get_session
from app.integrations.openclaw_gateway import (
    GatewayConfig,
    OpenClawGatewayError,
    delete_session,
    ensure_session,
    send_message,
)
from app.models.agents import Agent
from app.models.activity_events import ActivityEvent
from app.models.boards import Board
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentRead,
    AgentUpdate,
)
from app.services.activity_log import record_activity
from app.services.agent_provisioning import send_provisioning_message

router = APIRouter(prefix="/agents", tags=["agents"])

OFFLINE_AFTER = timedelta(minutes=10)
AGENT_SESSION_PREFIX = "agent"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _build_session_key(agent_name: str) -> str:
    return f"{AGENT_SESSION_PREFIX}:{_slugify(agent_name)}:main"


def _require_board(session: Session, board_id: UUID | str | None) -> Board:
    if not board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_id is required",
        )
    board = session.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    return board


def _require_gateway_config(board: Board) -> GatewayConfig:
    if not board.gateway_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_url is required",
        )
    return GatewayConfig(url=board.gateway_url, token=board.gateway_token)


async def _ensure_gateway_session(
    agent_name: str,
    config: GatewayConfig,
) -> tuple[str, str | None]:
    session_key = _build_session_key(agent_name)
    try:
        await ensure_session(session_key, config=config, label=agent_name)
        return session_key, None
    except OpenClawGatewayError as exc:
        return session_key, str(exc)


def _with_computed_status(agent: Agent) -> Agent:
    now = datetime.utcnow()
    if agent.last_seen_at is None:
        agent.status = "provisioning"
    elif now - agent.last_seen_at > OFFLINE_AFTER:
        agent.status = "offline"
    return agent


def _record_heartbeat(session: Session, agent: Agent) -> None:
    record_activity(
        session,
        event_type="agent.heartbeat",
        message=f"Heartbeat received from {agent.name}.",
        agent_id=agent.id,
    )


def _record_provisioning_failure(session: Session, agent: Agent, error: str) -> None:
    record_activity(
        session,
        event_type="agent.provision.failed",
        message=f"Provisioning message failed: {error}",
        agent_id=agent.id,
    )


def _record_wakeup_failure(session: Session, agent: Agent, error: str) -> None:
    record_activity(
        session,
        event_type="agent.wakeup.failed",
        message=f"Wakeup message failed: {error}",
        agent_id=agent.id,
    )


async def _send_wakeup_message(agent: Agent, config: GatewayConfig) -> None:
    session_key = agent.openclaw_session_id or _build_session_key(agent.name)
    message = (
        f"Hello {agent.name}. Your workspace has been provisioned.\n\n"
        "Start the agent, run BOOT.md, and if BOOTSTRAP.md exists run it once "
        "then delete it. Begin heartbeats after startup."
    )
    await send_message(message, session_key=session_key, config=config, deliver=True)


@router.get("", response_model=list[AgentRead])
def list_agents(
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> list[Agent]:
    agents = list(session.exec(select(Agent)))
    return [_with_computed_status(agent) for agent in agents]


@router.post("", response_model=AgentRead)
async def create_agent(
    payload: AgentCreate,
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> Agent:
    board = _require_board(session, payload.board_id)
    config = _require_gateway_config(board)
    agent = Agent.model_validate(payload)
    agent.status = "provisioning"
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    session_key, session_error = await _ensure_gateway_session(agent.name, config)
    agent.openclaw_session_id = session_key
    session.add(agent)
    session.commit()
    session.refresh(agent)
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
    session.commit()
    try:
        await send_provisioning_message(agent, board, raw_token)
        await _send_wakeup_message(agent, config)
        record_activity(
            session,
            event_type="agent.wakeup.sent",
            message=f"Wakeup message sent to {agent.name}.",
            agent_id=agent.id,
        )
    except OpenClawGatewayError as exc:
        _record_provisioning_failure(session, agent, str(exc))
        _record_wakeup_failure(session, agent, str(exc))
        session.commit()
    except Exception as exc:  # pragma: no cover - unexpected provisioning errors
        _record_provisioning_failure(session, agent, str(exc))
        _record_wakeup_failure(session, agent, str(exc))
        session.commit()
    return agent


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: str,
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _with_computed_status(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="status is controlled by agent heartbeat",
        )
    if "board_id" in updates and updates["board_id"]:
        _require_board(session, str(updates["board_id"]))
    for key, value in updates.items():
        setattr(agent, key, value)
    agent.updated_at = datetime.utcnow()
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return _with_computed_status(agent)


@router.post("/{agent_id}/heartbeat", response_model=AgentRead)
def heartbeat_agent(
    agent_id: str,
    payload: AgentHeartbeat,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent" and actor.agent and actor.agent.id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if payload.status:
        agent.status = payload.status
    elif agent.status == "provisioning":
        agent.status = "online"
    agent.last_seen_at = datetime.utcnow()
    agent.updated_at = datetime.utcnow()
    _record_heartbeat(session, agent)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return _with_computed_status(agent)


@router.post("/heartbeat", response_model=AgentRead)
async def heartbeat_or_create_agent(
    payload: AgentHeartbeatCreate,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> Agent:
    agent = session.exec(select(Agent).where(Agent.name == payload.name)).first()
    if agent is None:
        if actor.actor_type == "agent":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        board = _require_board(session, payload.board_id)
        config = _require_gateway_config(board)
        agent = Agent(name=payload.name, status="provisioning", board_id=board.id)
        raw_token = generate_agent_token()
        agent.agent_token_hash = hash_agent_token(raw_token)
        session_key, session_error = await _ensure_gateway_session(agent.name, config)
        agent.openclaw_session_id = session_key
        session.add(agent)
        session.commit()
        session.refresh(agent)
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
        session.commit()
        try:
            await send_provisioning_message(agent, board, raw_token)
            await _send_wakeup_message(agent, config)
            record_activity(
                session,
                event_type="agent.wakeup.sent",
                message=f"Wakeup message sent to {agent.name}.",
                agent_id=agent.id,
            )
        except OpenClawGatewayError as exc:
            _record_provisioning_failure(session, agent, str(exc))
            _record_wakeup_failure(session, agent, str(exc))
            session.commit()
        except Exception as exc:  # pragma: no cover - unexpected provisioning errors
            _record_provisioning_failure(session, agent, str(exc))
            _record_wakeup_failure(session, agent, str(exc))
            session.commit()
    elif actor.actor_type == "agent" and actor.agent and actor.agent.id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    elif agent.agent_token_hash is None and actor.actor_type == "user":
        raw_token = generate_agent_token()
        agent.agent_token_hash = hash_agent_token(raw_token)
        session.add(agent)
        session.commit()
        session.refresh(agent)
        try:
            board = _require_board(session, str(agent.board_id) if agent.board_id else None)
            config = _require_gateway_config(board)
            await send_provisioning_message(agent, board, raw_token)
            await _send_wakeup_message(agent, config)
            record_activity(
                session,
                event_type="agent.wakeup.sent",
                message=f"Wakeup message sent to {agent.name}.",
                agent_id=agent.id,
            )
        except OpenClawGatewayError as exc:
            _record_provisioning_failure(session, agent, str(exc))
            _record_wakeup_failure(session, agent, str(exc))
            session.commit()
        except Exception as exc:  # pragma: no cover - unexpected provisioning errors
            _record_provisioning_failure(session, agent, str(exc))
            _record_wakeup_failure(session, agent, str(exc))
            session.commit()
    elif not agent.openclaw_session_id:
        board = _require_board(session, str(agent.board_id) if agent.board_id else None)
        config = _require_gateway_config(board)
        session_key, session_error = await _ensure_gateway_session(agent.name, config)
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
        session.commit()
    if payload.status:
        agent.status = payload.status
    elif agent.status == "provisioning":
        agent.status = "online"
    agent.last_seen_at = datetime.utcnow()
    agent.updated_at = datetime.utcnow()
    _record_heartbeat(session, agent)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return _with_computed_status(agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: str,
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> dict[str, bool]:
    agent = session.get(Agent, agent_id)
    if agent:
        board = _require_board(session, str(agent.board_id) if agent.board_id else None)
        config = _require_gateway_config(board)
        async def _gateway_cleanup() -> None:
            if agent.openclaw_session_id:
                await delete_session(agent.openclaw_session_id, config=config)
            main_session = board.gateway_main_session_key or "agent:main:main"
            if main_session:
                workspace_root = (
                    board.gateway_workspace_root or "~/.openclaw/workspaces"
                )
                workspace_path = f"{workspace_root.rstrip('/')}/{_slugify(agent.name)}"
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
                await ensure_session(main_session, config=config, label="Main Agent")
                await send_message(
                    cleanup_message,
                    session_key=main_session,
                    config=config,
                    deliver=False,
                )

        try:
            import asyncio

            asyncio.run(_gateway_cleanup())
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gateway cleanup failed: {exc}",
            ) from exc
        session.execute(
            update(ActivityEvent)
            .where(col(ActivityEvent.agent_id) == agent.id)
            .values(agent_id=None)
        )
        session.delete(agent)
        session.commit()
    return {"ok": True}
