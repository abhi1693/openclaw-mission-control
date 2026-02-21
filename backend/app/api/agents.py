"""Thin API wrappers for async agent lifecycle operations."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, require_admin_or_agent, require_org_admin
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentRead,
    AgentUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.gateway_manager import gateway_manager
from app.services.openclaw.provisioning_db import AgentLifecycleService, AgentUpdateOptions
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

BOARD_ID_QUERY = Query(default=None)
GATEWAY_ID_QUERY = Query(default=None)
SINCE_QUERY = Query(default=None)
SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)
ACTOR_DEP = Depends(require_admin_or_agent)
AUTH_DEP = Depends(get_auth_context)


@dataclass(frozen=True, slots=True)
class _AgentUpdateParams:
    force: bool
    auth: AuthContext
    ctx: OrganizationContext


def _agent_update_params(
    *,
    force: bool = False,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> _AgentUpdateParams:
    return _AgentUpdateParams(force=force, auth=auth, ctx=ctx)


AGENT_UPDATE_PARAMS_DEP = Depends(_agent_update_params)


@router.get("", response_model=DefaultLimitOffsetPage[AgentRead])
async def list_agents(
    board_id: UUID | None = BOARD_ID_QUERY,
    gateway_id: UUID | None = GATEWAY_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> LimitOffsetPage[AgentRead]:
    """List agents visible to the active organization admin."""
    service = AgentLifecycleService(session)
    return await service.list_agents(
        board_id=board_id,
        gateway_id=gateway_id,
        ctx=ctx,
    )


@router.get("/stream")
async def stream_agents(
    request: Request,
    board_id: UUID | None = BOARD_ID_QUERY,
    since: str | None = SINCE_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> EventSourceResponse:
    """Stream agent updates as SSE events."""
    service = AgentLifecycleService(session)
    return await service.stream_agents(
        request=request,
        board_id=board_id,
        since=since,
        ctx=ctx,
    )


@router.post("", response_model=AgentRead)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Create and provision an agent."""
    service = AgentLifecycleService(session)
    return await service.create_agent(payload=payload, actor=actor)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> AgentRead:
    """Get a single agent by id."""
    service = AgentLifecycleService(session)
    return await service.get_agent(agent_id=agent_id, ctx=ctx)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    params: _AgentUpdateParams = AGENT_UPDATE_PARAMS_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentRead:
    """Update agent metadata and optionally reprovision."""
    service = AgentLifecycleService(session)
    return await service.update_agent(
        agent_id=agent_id,
        payload=payload,
        options=AgentUpdateOptions(
            force=params.force,
            user=params.auth.user,
            context=params.ctx,
        ),
    )


@router.post("/{agent_id}/heartbeat", response_model=AgentRead)
async def heartbeat_agent(
    agent_id: str,
    payload: AgentHeartbeat,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Record a heartbeat for a specific agent."""
    service = AgentLifecycleService(session)
    return await service.heartbeat_agent(agent_id=agent_id, payload=payload, actor=actor)


@router.post("/heartbeat", response_model=AgentRead)
async def heartbeat_or_create_agent(
    payload: AgentHeartbeatCreate,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Heartbeat an existing agent or create/provision one if needed."""
    service = AgentLifecycleService(session)
    return await service.heartbeat_or_create_agent(payload=payload, actor=actor)


@router.delete("/{agent_id}", response_model=OkResponse)
async def delete_agent(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete an agent and clean related task state."""
    service = AgentLifecycleService(session)
    return await service.delete_agent(agent_id=agent_id, ctx=ctx)


@router.websocket("/{agent_id}/terminal")
async def agent_terminal_websocket(
    websocket: WebSocket,
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """WebSocket endpoint for interactive terminal sessions with an agent.

    This relays terminal I/O between the frontend terminal emulator and
    the agent's Claude Code session running on the gateway.

    Protocol:
    - Client sends: {"type": "input", "content": "..."} for terminal input
    - Client sends: {"type": "resize", "cols": N, "rows": M} for resize
    - Server sends: {"type": "output", "content": "..."} for terminal output
    - Server sends: {"type": "error", "message": "..."} for errors
    """
    from app.models.agents import Agent
    from app.models.gateways import Gateway
    from app.models.machines import Machine

    await websocket.accept()

    # Look up the agent
    try:
        agent_uuid = UUID(agent_id)
    except ValueError:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid agent ID format",
        }))
        await websocket.close(code=4000)
        return

    agent = await Agent.objects.by_id(agent_uuid).first(session)
    if agent is None:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Agent not found",
        }))
        await websocket.close(code=4004)
        return

    # Get the gateway for this agent
    gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
    if gateway is None:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Gateway not found for agent",
        }))
        await websocket.close(code=4004)
        return

    # Find a connected machine for this gateway's organization
    connected_gateway = None
    for machine_id in gateway_manager.connected_machines():
        gw = gateway_manager.get(machine_id)
        if gw and gw.organization_id == gateway.organization_id:
            connected_gateway = gw
            break

    if connected_gateway is None:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "No connected gateway available",
        }))
        await websocket.close(code=4003)
        return

    logger.info(
        "Terminal session started agent_id=%s gateway_machine_id=%s",
        agent_id,
        connected_gateway.machine_id,
    )

    # Set up terminal session with the gateway
    terminal_session_id = f"terminal_{agent_id}_{id(websocket)}"

    # Send start terminal request to gateway
    start_result = await gateway_manager.request_with_response(
        connected_gateway.machine_id,
        request_type="terminal_start",
        payload={
            "agent_id": agent_id,
            "session_id": terminal_session_id,
            "openclaw_session_id": agent.openclaw_session_id,
        },
        timeout=10.0,
    )

    if start_result is None or not start_result.get("ok"):
        error_msg = (
            start_result.get("error", "Failed to start terminal session")
            if start_result
            else "Gateway did not respond"
        )
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": error_msg,
        }))
        await websocket.close(code=4005)
        return

    # Register this WebSocket for receiving terminal output from gateway
    await gateway_manager.register_terminal_session(
        connected_gateway.machine_id,
        session_id=terminal_session_id,
        websocket=websocket,
    )

    try:
        while True:
            # Receive messages from frontend
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "input":
                    # Forward input to gateway
                    await gateway_manager.send_message(
                        connected_gateway.machine_id,
                        {
                            "type": "terminal_input",
                            "session_id": terminal_session_id,
                            "content": data.get("content", ""),
                        },
                    )
                elif msg_type == "resize":
                    # Forward resize to gateway
                    await gateway_manager.send_message(
                        connected_gateway.machine_id,
                        {
                            "type": "terminal_resize",
                            "session_id": terminal_session_id,
                            "cols": data.get("cols", 80),
                            "rows": data.get("rows", 24),
                        },
                    )
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from terminal client")

    except WebSocketDisconnect:
        logger.info("Terminal session disconnected agent_id=%s", agent_id)
    except Exception as e:
        logger.error("Terminal session error agent_id=%s error=%s", agent_id, str(e))
    finally:
        # Clean up terminal session
        await gateway_manager.unregister_terminal_session(
            connected_gateway.machine_id,
            session_id=terminal_session_id,
        )

        # Send stop terminal request to gateway
        await gateway_manager.send_message(
            connected_gateway.machine_id,
            {
                "type": "terminal_stop",
                "session_id": terminal_session_id,
            },
        )

        logger.info("Terminal session cleanup complete agent_id=%s", agent_id)
