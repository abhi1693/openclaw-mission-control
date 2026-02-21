"""Gateway manager for tracking active dial-home WebSocket connections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.time import utcnow

if TYPE_CHECKING:
    from websockets import WebSocketServerProtocol


@dataclass
class ConnectedGateway:
    """Represents an active gateway connection."""

    machine_id: UUID
    organization_id: UUID
    connection_id: int  # DB id from gateway_connections table
    websocket: Any  # WebSocket connection (FastAPI WebSocket or websockets)
    connected_at: datetime = field(default_factory=utcnow)
    last_heartbeat_at: datetime = field(default_factory=utcnow)
    gateway_version: str | None = None
    agents_managed: int = 0
    pending_requests: dict[str, asyncio.Future] = field(default_factory=dict)
    terminal_sessions: dict[str, Any] = field(default_factory=dict)  # session_id -> client websocket


class GatewayManager:
    """Manages active gateway connections across the platform."""

    def __init__(self) -> None:
        self._connections: dict[UUID, ConnectedGateway] = {}  # machine_id -> gateway
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        machine_id: UUID,
        organization_id: UUID,
        connection_id: int,
        websocket: Any,
        gateway_version: str | None = None,
    ) -> ConnectedGateway:
        """Register a new gateway connection."""
        async with self._lock:
            # Close existing connection for this machine if any
            if machine_id in self._connections:
                existing = self._connections[machine_id]
                try:
                    await existing.websocket.close()
                except Exception:
                    pass

            gateway = ConnectedGateway(
                machine_id=machine_id,
                organization_id=organization_id,
                connection_id=connection_id,
                websocket=websocket,
                gateway_version=gateway_version,
            )
            self._connections[machine_id] = gateway
            return gateway

    async def unregister(self, machine_id: UUID) -> None:
        """Remove a gateway connection."""
        async with self._lock:
            if machine_id in self._connections:
                gateway = self._connections.pop(machine_id)
                # Cancel any pending requests
                for request_id, future in gateway.pending_requests.items():
                    if not future.done():
                        future.cancel()

    def get(self, machine_id: UUID) -> ConnectedGateway | None:
        """Get a connected gateway by machine ID."""
        return self._connections.get(machine_id)

    def get_by_organization(self, organization_id: UUID) -> list[ConnectedGateway]:
        """Get all connected gateways for an organization."""
        return [
            gw for gw in self._connections.values()
            if gw.organization_id == organization_id
        ]

    def is_connected(self, machine_id: UUID) -> bool:
        """Check if a machine's gateway is connected."""
        return machine_id in self._connections

    def connected_count(self) -> int:
        """Get the total number of connected gateways."""
        return len(self._connections)

    def connected_machines(self) -> list[UUID]:
        """Get list of all connected machine IDs."""
        return list(self._connections.keys())

    async def update_heartbeat(
        self,
        machine_id: UUID,
        *,
        agents_managed: int | None = None,
    ) -> None:
        """Update the heartbeat timestamp for a gateway."""
        gateway = self._connections.get(machine_id)
        if gateway is not None:
            gateway.last_heartbeat_at = utcnow()
            if agents_managed is not None:
                gateway.agents_managed = agents_managed

    async def send_message(
        self,
        machine_id: UUID,
        message: dict,
    ) -> bool:
        """Send a message to a specific gateway."""
        gateway = self._connections.get(machine_id)
        if gateway is None:
            return False

        try:
            import json
            await gateway.websocket.send_text(json.dumps(message))
            return True
        except Exception:
            # Connection failed, remove it
            await self.unregister(machine_id)
            return False

    async def send_task(
        self,
        machine_id: UUID,
        *,
        task_id: UUID,
        queue_entry_id: int,
        payload: dict,
    ) -> bool:
        """Send a task to a gateway for dispatch."""
        message = {
            "type": "task",
            "task_id": str(task_id),
            "queue_entry_id": queue_entry_id,
            "payload": payload,
        }
        return await self.send_message(machine_id, message)

    async def request_with_response(
        self,
        machine_id: UUID,
        *,
        request_type: str,
        payload: dict,
        timeout: float = 30.0,
    ) -> dict | None:
        """Send a request to a gateway and wait for a response."""
        gateway = self._connections.get(machine_id)
        if gateway is None:
            return None

        import json
        import uuid

        request_id = str(uuid.uuid4())
        message = {
            "type": request_type,
            "request_id": request_id,
            "payload": payload,
        }

        # Create a future for the response
        future: asyncio.Future[dict] = asyncio.Future()
        gateway.pending_requests[request_id] = future

        try:
            await gateway.websocket.send_text(json.dumps(message))
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        finally:
            gateway.pending_requests.pop(request_id, None)

    async def handle_response(
        self,
        machine_id: UUID,
        *,
        request_id: str,
        response: dict,
    ) -> None:
        """Handle a response from a gateway."""
        gateway = self._connections.get(machine_id)
        if gateway is None:
            return

        future = gateway.pending_requests.get(request_id)
        if future is not None and not future.done():
            future.set_result(response)

    async def broadcast_to_organization(
        self,
        organization_id: UUID,
        message: dict,
    ) -> int:
        """Broadcast a message to all gateways in an organization."""
        gateways = self.get_by_organization(organization_id)
        sent_count = 0

        for gateway in gateways:
            if await self.send_message(gateway.machine_id, message):
                sent_count += 1

        return sent_count

    def get_stats(self) -> dict:
        """Get statistics about connected gateways."""
        total_agents = sum(gw.agents_managed for gw in self._connections.values())
        orgs = set(gw.organization_id for gw in self._connections.values())
        total_terminal_sessions = sum(
            len(gw.terminal_sessions) for gw in self._connections.values()
        )

        return {
            "connected_gateways": len(self._connections),
            "total_agents_managed": total_agents,
            "organizations": len(orgs),
            "terminal_sessions": total_terminal_sessions,
        }

    async def register_terminal_session(
        self,
        machine_id: UUID,
        *,
        session_id: str,
        websocket: Any,
    ) -> None:
        """Register a terminal session WebSocket for receiving output."""
        gateway = self._connections.get(machine_id)
        if gateway is not None:
            gateway.terminal_sessions[session_id] = websocket

    async def unregister_terminal_session(
        self,
        machine_id: UUID,
        *,
        session_id: str,
    ) -> None:
        """Unregister a terminal session WebSocket."""
        gateway = self._connections.get(machine_id)
        if gateway is not None:
            gateway.terminal_sessions.pop(session_id, None)

    async def relay_terminal_output(
        self,
        machine_id: UUID,
        *,
        session_id: str,
        content: str,
    ) -> bool:
        """Relay terminal output from gateway to client WebSocket."""
        gateway = self._connections.get(machine_id)
        if gateway is None:
            return False

        client_ws = gateway.terminal_sessions.get(session_id)
        if client_ws is None:
            return False

        try:
            import json
            await client_ws.send_text(json.dumps({
                "type": "output",
                "content": content,
            }))
            return True
        except Exception:
            # Client disconnected, clean up
            gateway.terminal_sessions.pop(session_id, None)
            return False

    def get_terminal_session(
        self,
        machine_id: UUID,
        session_id: str,
    ) -> Any | None:
        """Get a terminal session WebSocket if it exists."""
        gateway = self._connections.get(machine_id)
        if gateway is None:
            return None
        return gateway.terminal_sessions.get(session_id)


# Global gateway manager instance
gateway_manager = GatewayManager()
