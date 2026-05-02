"""DB-backed gateway config resolution and message dispatch helpers.

This module exists to keep `app.api.*` thin: APIs should call OpenClaw services, not
directly orchestrate gateway RPC calls.
"""

from __future__ import annotations

import asyncio
from typing import Final
from uuid import uuid4

from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    get_gateway_for_board,
    optional_gateway_client_config,
    require_gateway_for_board,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    abort_session,
    ensure_session,
    send_message,
)

# Hard ceiling on agent-notify gateway calls to prevent the
# best-effort notify path from wedging caller request threads when
# the gateway WebSocket hangs. Two repros on 2026-05-02:
#   - Comment POST on E.3 returned after 3,757,043 ms (62 min)
#   - Comment POST on E.3 returned after 4,484,215 ms (74 min)
# In both cases the gateway was unresponsive, ``send_message`` blocked
# on the WebSocket await, and the comment-notify call site held the
# MC request open for the full duration. Notifications are best-effort
# (the comment is already committed before notify fires), so a
# bounded timeout is the right contract: the notify either succeeds
# fast or surfaces a ``OpenClawGatewayError`` and the caller logs the
# miss and moves on. 30 seconds covers normal gateway latency
# (typical p95 < 1 s) plus a generous margin for ACPX cold starts;
# anything beyond that is a hung gateway, not a slow one.
GATEWAY_NOTIFY_TIMEOUT_SECONDS: Final[float] = 30.0


class GatewayDispatchService(OpenClawDBService):
    """Resolve gateway config for boards and dispatch messages to agent sessions."""

    async def optional_gateway_config_for_board(
        self,
        board: Board,
    ) -> GatewayClientConfig | None:
        gateway = await get_gateway_for_board(self.session, board)
        return optional_gateway_client_config(gateway)

    async def require_gateway_config_for_board(
        self,
        board: Board,
    ) -> tuple[Gateway, GatewayClientConfig]:
        gateway = await require_gateway_for_board(self.session, board)
        return gateway, gateway_client_config(gateway)

    async def send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        await ensure_session(session_key, config=config, label=agent_name)
        await send_message(message, session_key=session_key, config=config, deliver=deliver)

    async def try_send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> OpenClawGatewayError | None:
        try:
            await asyncio.wait_for(
                self.send_agent_message(
                    session_key=session_key,
                    config=config,
                    agent_name=agent_name,
                    message=message,
                    deliver=deliver,
                ),
                timeout=GATEWAY_NOTIFY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return OpenClawGatewayError(
                "gateway notify timeout: send_agent_message did not return "
                f"within {GATEWAY_NOTIFY_TIMEOUT_SECONDS}s "
                f"(session_key={session_key}, agent={agent_name})",
            )
        except OpenClawGatewayError as exc:
            return exc
        return None

    async def abort_agent_session(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
    ) -> OpenClawGatewayError | None:
        """Abort the current run in a session, ignoring errors."""
        try:
            await abort_session(session_key, config=config)
        except OpenClawGatewayError as exc:
            return exc
        return None

    @staticmethod
    def resolve_trace_id(correlation_id: str | None, *, prefix: str) -> str:
        normalized = (correlation_id or "").strip()
        if normalized:
            return normalized
        return f"{prefix}:{uuid4().hex[:12]}"
