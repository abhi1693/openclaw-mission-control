"""Gateway listener manager for maintaining persistent WebSocket connections to all gateways."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.logging import get_logger
from app.models.gateways import Gateway
from app.services.openclaw.gateway_events import PerGatewayConnection

if TYPE_CHECKING:
    from app.db.session import AsyncSession

logger = get_logger(__name__)


class GatewayListenerManager:
    """Manages persistent WebSocket connections to all configured gateways.

    This singleton coordinates lifecycle events for all gateway listeners,
    starting connections on application startup and stopping them on shutdown.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, PerGatewayConnection] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def start_for_gateway(self, gateway: Gateway) -> None:
        """Start event listening for a specific gateway.

        If a connection already exists for this gateway, it will be replaced.
        """
        async with self._lock:
            if gateway.id in self._connections:
                logger.warning(
                    "gateway.listener_manager.already_running gateway_id=%s",
                    gateway.id,
                )
                await self._connections[gateway.id].disconnect()

            connection = PerGatewayConnection(gateway)
            try:
                await connection.connect()
                self._connections[gateway.id] = connection
                logger.info(
                    "gateway.listener_manager.started gateway_id=%s",
                    gateway.id,
                )
            except Exception:
                logger.exception(
                    "gateway.listener_manager.start_failed gateway_id=%s",
                    gateway.id,
                )

    async def stop_for_gateway(self, gateway_id: UUID) -> None:
        """Stop event listening for a specific gateway."""
        async with self._lock:
            connection = self._connections.pop(gateway_id, None)
            if connection is not None:
                await connection.disconnect()
                logger.info(
                    "gateway.listener_manager.stopped gateway_id=%s",
                    gateway_id,
                )
            else:
                logger.warning(
                    "gateway.listener_manager.not_running gateway_id=%s",
                    gateway_id,
                )

    async def stop_all(self) -> None:
        """Stop all active gateway connections."""
        async with self._lock:
            gateway_ids = list(self._connections.keys())
        for gateway_id in gateway_ids:
            await self.stop_for_gateway(gateway_id)
        logger.info("gateway.listener_manager.stopped_all")

    async def start_all(self) -> None:
        """Start event listening for all gateways in the database."""
        from app.db.session import async_session_maker
        from app.services.openclaw.admin_service import GatewayAdminLifecycleService

        async with async_session_maker() as session:
            gateways = await Gateway.objects.all().all(session)
            # Ensure gateway-main agents exist and have correct approval_policy
            service = GatewayAdminLifecycleService(session)
            await service.ensure_gateway_agents_exist(gateways)
            await session.commit()
        for gateway in gateways:
            await self.start_for_gateway(gateway)


gateway_listener_manager = GatewayListenerManager()
