"""Gateway event listener for a single Gateway's persistent WebSocket connection."""

from __future__ import annotations

import asyncio
import json
import ssl
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import UUID, uuid4

import websockets
from websockets.exceptions import WebSocketException

from app.core.logging import TRACE_LEVEL, get_logger
from app.services.openclaw.approval_policy import apply_approval_policy
from app.services.openclaw.gateway_resolver import gateway_client_config
from app.services.openclaw.gateway_rpc import (
    CONTROL_UI_CLIENT_ID,
    CONTROL_UI_CLIENT_MODE,
    DEFAULT_GATEWAY_CLIENT_ID,
    DEFAULT_GATEWAY_CLIENT_MODE,
    GATEWAY_OPERATOR_SCOPES,
    PROTOCOL_VERSION,
    GatewayConfig,
    _build_control_ui_origin,
    _build_device_connect_payload,
    _create_ssl_context,
    _resolve_connect_mode,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.agents import Agent
    from app.models.gateways import Gateway

logger = get_logger(__name__)


class PerGatewayConnection:
    """Manages a persistent WebSocket connection to a single Gateway.

    Handles the connection lifecycle, event listening, and dispatches events
    to appropriate handlers.
    """

    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway
        self._config: GatewayConfig = gateway_client_config(gateway)
        self._ws: websockets.ClientConnection | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()

    @property
    def gateway_id(self) -> UUID:
        """Return the gateway ID for this connection."""
        return self._gateway.id

    def _build_gateway_url(self) -> str:
        """Build the WebSocket URL for this gateway."""
        base_url = (self._config.url or "").strip()
        if not base_url:
            raise ValueError("Gateway URL is not configured")
        token = self._config.token
        if not token:
            return base_url
        parsed = urlparse(base_url)
        query = urlencode({"token": token})
        return str(urlunparse(parsed._replace(query=query)))

    async def connect(self) -> None:
        """Establish the WebSocket connection and start listening for events."""
        gateway_url = self._build_gateway_url()
        logger.info(
            "gateway.listener.connecting gateway_id=%s url=%s",
            self._gateway.id,
            self._redacted_url(gateway_url),
        )

        ssl_context = _create_ssl_context(self._config)
        connect_kwargs: dict[str, Any] = {"ping_interval": None}

        origin = (
            _build_control_ui_origin(gateway_url) if self._config.disable_device_pairing else None
        )
        if origin is not None:
            connect_kwargs["origin"] = origin
        if ssl_context is not None:
            connect_kwargs["ssl"] = ssl_context

        try:
            self._ws = await websockets.connect(gateway_url, **connect_kwargs)
            self._shutdown_event.clear()

            # Wait for the initial challenge message with a timeout
            try:
                first_message = await asyncio.wait_for(self._ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(
                    "gateway.listener.challenge_timeout gateway_id=%s",
                    self._gateway.id,
                )
                raise

            if isinstance(first_message, bytes):
                first_message = first_message.decode("utf-8")
            challenge_data = json.loads(first_message)

            connect_nonce: str | None = None
            if (
                challenge_data.get("type") == "event"
                and challenge_data.get("event") == "connect.challenge"
            ):
                payload = challenge_data.get("payload")
                if isinstance(payload, dict):
                    nonce = payload.get("nonce")
                    if isinstance(nonce, str) and nonce.strip():
                        connect_nonce = nonce.strip()

            # Build and send connect request
            role = "operator"
            scopes = list(GATEWAY_OPERATOR_SCOPES)
            connect_mode = _resolve_connect_mode(self._config)
            use_control_ui = connect_mode == "control_ui"

            params: dict[str, Any] = {
                "minProtocol": PROTOCOL_VERSION,
                "maxProtocol": PROTOCOL_VERSION,
                "role": role,
                "scopes": scopes,
                "client": {
                    "id": CONTROL_UI_CLIENT_ID if use_control_ui else DEFAULT_GATEWAY_CLIENT_ID,
                    "version": "1.0.0",
                    "platform": "python",
                    "mode": (
                        CONTROL_UI_CLIENT_MODE if use_control_ui else DEFAULT_GATEWAY_CLIENT_MODE
                    ),
                },
            }
            if not use_control_ui:
                params["device"] = _build_device_connect_payload(
                    client_id=DEFAULT_GATEWAY_CLIENT_ID,
                    client_mode=DEFAULT_GATEWAY_CLIENT_MODE,
                    role=role,
                    scopes=scopes,
                    auth_token=self._config.token,
                    connect_nonce=connect_nonce,
                )
            if self._config.token:
                params["auth"] = {"token": self._config.token}

            request_id = str(uuid4())
            connect_request = {
                "type": "req",
                "id": request_id,
                "method": "connect",
                "params": params,
            }
            await self._ws.send(json.dumps(connect_request))

            # Wait for connect response with timeout - listener loop starts after this
            # so there's no concurrency issue here
            try:
                while True:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
                    data = json.loads(raw)
                    if data.get("type") == "res" and data.get("id") == request_id:
                        ok = data.get("ok")
                        if ok is False:
                            error = data.get("error", {}).get("message", "Connect failed")
                            raise RuntimeError(f"Gateway connect rejected: {error}")
                        logger.debug(
                            "gateway.listener.connected gateway_id=%s",
                            self._gateway.id,
                        )
                        break
            except asyncio.TimeoutError:
                logger.warning(
                    "gateway.listener.connect_response_timeout gateway_id=%s",
                    self._gateway.id,
                )
                await asyncio.sleep(1)
                raise

            self._listener_task = asyncio.create_task(self._listen_loop())
            logger.info("gateway.listener.started gateway_id=%s", self._gateway.id)

        except Exception:
            # Ensure WebSocket is closed and cleaned up on any failure
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None
            raise

    def _redacted_url(self, raw_url: str) -> str:
        """Return URL with query params redacted for logging."""
        parsed = urlparse(raw_url)
        return str(urlunparse(parsed._replace(query="", fragment="")))

    async def _listen_loop(self) -> None:
        """Continuously receive and process events from the gateway."""
        while not self._shutdown_event.is_set() and self._ws is not None:
            try:
                msg = await self._ws.recv()
                event = json.loads(msg)
                logger.log(
                    TRACE_LEVEL,
                    "gateway.listener.event gateway_id=%s event=%s",
                    self._gateway.id,
                    event.get("event"),
                )
                await self._dispatch_event(event)
            except (websockets.ConnectionClosed, websockets.exceptions.ConcurrencyError):
                if not self._shutdown_event.is_set():
                    logger.warning(
                        "gateway.listener.connection_lost gateway_id=%s", self._gateway.id
                    )
                    await self._reconnect()
            except Exception:
                logger.exception("gateway.listener.error gateway_id=%s", self._gateway.id)
                if not self._shutdown_event.is_set():
                    await asyncio.sleep(1)

    async def _reconnect(self) -> None:
        """Attempt to reconnect after a connection loss."""
        if self._shutdown_event.is_set():
            return
        for attempt in range(5):
            wait_time = min(2**attempt, 30)
            logger.info(
                "gateway.listener.reconnecting gateway_id=%s attempt=%s wait=%s",
                self._gateway.id,
                attempt + 1,
                wait_time,
            )
            await asyncio.sleep(wait_time)
            try:
                await self.connect()
                return
            except Exception:
                logger.exception(
                    "gateway.listener.reconnect_failed gateway_id=%s", self._gateway.id
                )
        logger.error("gateway.listener.reconnect_exhausted gateway_id=%s", self._gateway.id)

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        """Route events to their appropriate handlers."""
        event_type = event.get("event")
        if event_type == "exec.approval.requested":
            await self._handle_approval_requested(event)
        elif event_type == "exec.approval.resolved":
            await self._handle_approval_resolved(event)

    async def _handle_approval_requested(self, event: dict[str, Any]) -> None:
        """Handle exec.approval.requested events from the gateway."""
        from uuid import UUID as UUIDCls

        from sqlmodel import col, select

        from app.db.session import async_session_maker
        from app.models.agents import Agent
        from app.services.openclaw.internal.agent_key import agent_key as _agent_key
        from app.services.openclaw.shared import GatewayAgentIdentity

        payload = event.get("payload", {})
        request_data = payload.get("request", {})
        agent_id = request_data.get("agentId")
        if not agent_id:
            logger.warning(
                "gateway.listener.approval_requested.missing_agent_id gateway_id=%s",
                self._gateway.id,
            )
            return

        async with async_session_maker() as session:
            agent = await self._find_agent_by_openclaw_id(session, agent_id, self._gateway)
            if agent is None:
                logger.warning(
                    "gateway.listener.approval_requested.agent_not_found gateway_id=%s agent_id=%s",
                    self._gateway.id,
                    agent_id,
                )
                return

            auto_approved = await apply_approval_policy(
                agent=agent,
                gateway=self._gateway,
                approval_request=payload,
            )
            if auto_approved:
                logger.info(
                    "gateway.listener.auto_resolved gateway_id=%s agent_id=%s approval_id=%s",
                    self._gateway.id,
                    agent_id,
                    payload.get("approvalId"),
                )

    async def _find_agent_by_openclaw_id(
        self, session: "AsyncSession", openclaw_agent_id: str, gateway: "Gateway"
    ) -> "Agent | None":
        """Look up a Mission Control agent by its OpenClaw agent ID.

        The OpenClaw agent ID can be:
        - A UUID (backward compat - direct MC agent ID)
        - The gateway main agent ID: mc-gateway-{gateway_id}
        - A board lead agent ID: lead-{board_id}
        - Any agent with session_id like agent:{agent_key}:main
        """
        from uuid import UUID as UUIDCls

        from sqlmodel import col, select

        from app.models.agents import Agent
        from app.services.openclaw.internal.agent_key import agent_key as _agent_key
        from app.services.openclaw.shared import GatewayAgentIdentity

        # Try to parse as UUID first (backward compat)
        try:
            agent_uuid = UUIDCls(openclaw_agent_id)
            return await Agent.objects.by_id(agent_uuid).first(session)
        except (ValueError, TypeError):
            pass

        # Check if it's the gateway main agent
        gateway_main_openclaw_id = GatewayAgentIdentity.openclaw_agent_id(gateway)
        if openclaw_agent_id == gateway_main_openclaw_id:
            # Gateway main agent: board_id=None, is_board_lead=False
            stmt = (
                select(Agent)
                .where(Agent.gateway_id == gateway.id)
                .where(col(Agent.board_id).is_(None))
                .where(col(Agent.is_board_lead).is_(False))
            )
            return (await session.exec(stmt)).first()

        # Search all agents in this gateway by matching agent_key
        # For agents with session_id like agent:{agent_key}:main, agent_key() returns the key
        stmt = select(Agent).where(Agent.gateway_id == gateway.id)
        agents = (await session.exec(stmt)).all()
        for agent in agents:
            if _agent_key(agent) == openclaw_agent_id:
                return agent

        return None

    async def _handle_approval_resolved(self, event: dict[str, Any]) -> None:
        """Handle exec.approval.resolved events from the gateway."""
        payload = event.get("payload", {})
        logger.info(
            "gateway.listener.approval_resolved gateway_id=%s approval_id=%s",
            self._gateway.id,
            payload.get("id"),
        )

    async def disconnect(self) -> None:
        """Gracefully shut down the connection and listener task."""
        logger.info("gateway.listener.stopping gateway_id=%s", self._gateway.id)
        self._shutdown_event.set()
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        logger.info("gateway.listener.stopped gateway_id=%s", self._gateway.id)
