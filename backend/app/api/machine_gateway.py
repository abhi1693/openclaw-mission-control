"""WebSocket endpoint for machine gateway dial-home connections."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.db.session import get_session
from app.services.gateway_manager import gateway_manager
from app.services.machine_token import (
    get_pending_tasks_for_machine,
    record_gateway_connect,
    record_gateway_disconnect,
    update_gateway_heartbeat,
    verify_machine_token,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)
router = APIRouter(prefix="/gateway", tags=["machine-gateway"])

HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 90  # seconds


async def _authenticate_gateway(
    websocket: WebSocket,
    token: str,
    session: AsyncSession,
) -> tuple[bool, dict | None]:
    """Authenticate gateway connection via machine token."""
    ctx = await verify_machine_token(session, raw_token=token)
    if ctx is None:
        return False, None

    return True, {
        "machine_id": ctx.machine.id,
        "organization_id": ctx.organization_id,
        "machine_name": ctx.machine.name,
        "scopes": ctx.token.scopes,
    }


async def _send_pending_tasks(
    websocket: WebSocket,
    machine_id,
    session: AsyncSession,
) -> None:
    """Send any pending tasks to the gateway."""
    from app.models.tasks import Task

    tasks = await get_pending_tasks_for_machine(
        session,
        machine_id=machine_id,
        limit=10,
    )

    for queue_entry in tasks:
        # Load the task details
        task = await Task.objects.by_id(queue_entry.task_id).first(session)
        if task is None:
            continue

        message = {
            "type": "task",
            "queue_entry_id": queue_entry.id,
            "task_id": str(task.id),
            "payload": {
                "objective": task.objective,
                "context": task.context,
                "status": task.status,
                "board_id": str(task.board_id),
            },
        }
        await websocket.send_text(json.dumps(message))


async def _handle_heartbeat(
    websocket: WebSocket,
    machine_id,
    connection_id: int,
    data: dict,
    session: AsyncSession,
) -> None:
    """Handle heartbeat message from gateway."""
    agents_managed = data.get("agents_managed")

    # Update in-memory state
    await gateway_manager.update_heartbeat(
        machine_id,
        agents_managed=agents_managed,
    )

    # Update database
    await update_gateway_heartbeat(
        session,
        connection_id=connection_id,
        agents_managed=agents_managed,
    )

    # Send pong response
    await websocket.send_text(json.dumps({
        "type": "pong",
        "timestamp": data.get("timestamp"),
    }))


async def _handle_task_ack(
    websocket: WebSocket,
    data: dict,
    session: AsyncSession,
) -> None:
    """Handle task acknowledgment from gateway."""
    from app.services.machine_token import acknowledge_task

    queue_entry_id = data.get("queue_entry_id")
    if queue_entry_id is not None:
        await acknowledge_task(session, queue_entry_id=queue_entry_id)


async def _handle_task_dispatched(
    websocket: WebSocket,
    data: dict,
    session: AsyncSession,
) -> None:
    """Handle task dispatched notification from gateway."""
    from uuid import UUID
    from app.services.machine_token import mark_task_dispatched

    queue_entry_id = data.get("queue_entry_id")
    agent_id = data.get("agent_id")

    if queue_entry_id is not None and agent_id is not None:
        await mark_task_dispatched(
            session,
            queue_entry_id=queue_entry_id,
            agent_id=UUID(agent_id),
        )


async def _handle_task_completed(
    websocket: WebSocket,
    data: dict,
    session: AsyncSession,
) -> None:
    """Handle task completed notification from gateway."""
    from app.services.machine_token import mark_task_completed

    queue_entry_id = data.get("queue_entry_id")
    if queue_entry_id is not None:
        await mark_task_completed(session, queue_entry_id=queue_entry_id)


async def _handle_response(
    websocket: WebSocket,
    machine_id,
    data: dict,
) -> None:
    """Handle response to a previous request."""
    request_id = data.get("request_id")
    response = data.get("response", {})

    if request_id:
        await gateway_manager.handle_response(
            machine_id,
            request_id=request_id,
            response=response,
        )


async def _handle_agent_status(
    websocket: WebSocket,
    data: dict,
    session: AsyncSession,
) -> None:
    """Handle agent status update from gateway."""
    from uuid import UUID
    from app.models.agents import Agent
    from app.core.time import utcnow

    agent_id = data.get("agent_id")
    status = data.get("status")

    if agent_id and status:
        agent = await Agent.objects.by_id(UUID(agent_id)).first(session)
        if agent:
            agent.status = status
            agent.last_heartbeat_at = utcnow()
            session.add(agent)
            await session.commit()


async def _handle_terminal_output(
    websocket: WebSocket,
    machine_id,
    data: dict,
) -> None:
    """Handle terminal output from gateway, relay to client."""
    session_id = data.get("session_id")
    content = data.get("content", "")

    if session_id:
        await gateway_manager.relay_terminal_output(
            machine_id,
            session_id=session_id,
            content=content,
        )


async def _process_message(
    websocket: WebSocket,
    machine_id,
    connection_id: int,
    message: str,
    session: AsyncSession,
) -> None:
    """Process incoming WebSocket message."""
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON from gateway machine_id=%s", machine_id)
        return

    msg_type = data.get("type")

    handlers = {
        "heartbeat": lambda: _handle_heartbeat(
            websocket, machine_id, connection_id, data, session
        ),
        "ping": lambda: _handle_heartbeat(
            websocket, machine_id, connection_id, data, session
        ),
        "task_ack": lambda: _handle_task_ack(websocket, data, session),
        "task_dispatched": lambda: _handle_task_dispatched(websocket, data, session),
        "task_completed": lambda: _handle_task_completed(websocket, data, session),
        "response": lambda: _handle_response(websocket, machine_id, data),
        "agent_status": lambda: _handle_agent_status(websocket, data, session),
        "terminal_output": lambda: _handle_terminal_output(websocket, machine_id, data),
    }

    handler = handlers.get(msg_type)
    if handler:
        await handler()
    else:
        logger.debug(
            "Unknown message type from gateway type=%s machine_id=%s",
            msg_type,
            machine_id,
        )


@router.websocket("/connect")
async def gateway_connect(
    websocket: WebSocket,
    token: str = Query(..., description="Machine authentication token"),
    version: str = Query(default="unknown", description="Gateway daemon version"),
    session: AsyncSession = Depends(get_session),
) -> None:
    """WebSocket endpoint for gateway dial-home connections.

    Gateways authenticate using a machine token and maintain a persistent
    connection to receive tasks and send status updates.

    Protocol:
    - Gateway sends: heartbeat, task_ack, task_dispatched, task_completed, agent_status
    - Platform sends: task, ping, request (with response expected)
    """
    # Authenticate before accepting the connection
    authenticated, auth_info = await _authenticate_gateway(websocket, token, session)

    if not authenticated or auth_info is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()

    machine_id = auth_info["machine_id"]
    organization_id = auth_info["organization_id"]

    logger.info(
        "Gateway connected machine_id=%s organization_id=%s version=%s",
        machine_id,
        organization_id,
        version,
    )

    # Record connection in database
    connection = await record_gateway_connect(
        session,
        machine_id=machine_id,
        organization_id=organization_id,
        gateway_version=version,
    )

    # Register with in-memory manager
    await gateway_manager.register(
        machine_id=machine_id,
        organization_id=organization_id,
        connection_id=connection.id,
        websocket=websocket,
        gateway_version=version,
    )

    # Send welcome message
    await websocket.send_text(json.dumps({
        "type": "welcome",
        "machine_id": str(machine_id),
        "connection_id": connection.id,
    }))

    # Send any pending tasks
    await _send_pending_tasks(websocket, machine_id, session)

    try:
        while True:
            # Wait for messages with timeout
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_TIMEOUT,
                )
                await _process_message(
                    websocket,
                    machine_id,
                    connection.id,
                    message,
                    session,
                )
            except asyncio.TimeoutError:
                # No message received within timeout, send ping
                await websocket.send_text(json.dumps({
                    "type": "ping",
                    "timestamp": str(asyncio.get_event_loop().time()),
                }))
    except WebSocketDisconnect:
        logger.info("Gateway disconnected machine_id=%s", machine_id)
    except Exception as e:
        logger.error(
            "Gateway connection error machine_id=%s error=%s",
            machine_id,
            str(e),
        )
    finally:
        # Clean up
        await gateway_manager.unregister(machine_id)
        await record_gateway_disconnect(session, connection_id=connection.id)
        logger.info(
            "Gateway cleanup complete machine_id=%s connection_id=%s",
            machine_id,
            connection.id,
        )


@router.get("/stats")
async def gateway_stats() -> dict:
    """Get statistics about connected gateways."""
    return gateway_manager.get_stats()


@router.get("/connected")
async def connected_gateways(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all currently connected gateways."""
    from app.models.machines import Machine

    connected = []
    for machine_id in gateway_manager.connected_machines():
        gateway = gateway_manager.get(machine_id)
        if gateway is None:
            continue

        machine = await Machine.objects.by_id(machine_id).first(session)
        connected.append({
            "machine_id": str(machine_id),
            "machine_name": machine.name if machine else "Unknown",
            "organization_id": str(gateway.organization_id),
            "connected_at": gateway.connected_at.isoformat(),
            "last_heartbeat_at": gateway.last_heartbeat_at.isoformat(),
            "gateway_version": gateway.gateway_version,
            "agents_managed": gateway.agents_managed,
        })

    return connected
