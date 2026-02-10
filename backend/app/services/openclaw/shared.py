"""Shared OpenClaw lifecycle primitives."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import ensure_session, send_message
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.constants import (
    _GATEWAY_AGENT_PREFIX,
    _GATEWAY_AGENT_SUFFIX,
    _GATEWAY_OPENCLAW_AGENT_PREFIX,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


class GatewayAgentIdentity:
    """Naming and identity rules for Mission Control gateway-main agents."""

    @classmethod
    def session_key_for_id(cls, gateway_id: UUID) -> str:
        return f"{_GATEWAY_AGENT_PREFIX}{gateway_id}{_GATEWAY_AGENT_SUFFIX}"

    @classmethod
    def session_key(cls, gateway: Gateway) -> str:
        return cls.session_key_for_id(gateway.id)

    @classmethod
    def openclaw_agent_id_for_id(cls, gateway_id: UUID) -> str:
        return f"{_GATEWAY_OPENCLAW_AGENT_PREFIX}{gateway_id}"

    @classmethod
    def openclaw_agent_id(cls, gateway: Gateway) -> str:
        return cls.openclaw_agent_id_for_id(gateway.id)


async def optional_gateway_config_for_board(
    session: AsyncSession,
    board: Board,
) -> GatewayClientConfig | None:
    """Return gateway client config when board has a reachable configured gateway."""
    if board.gateway_id is None:
        return None
    gateway = await Gateway.objects.by_id(board.gateway_id).first(session)
    if gateway is None or not gateway.url:
        return None
    return GatewayClientConfig(url=gateway.url, token=gateway.token)


async def require_gateway_config_for_board(
    session: AsyncSession,
    board: Board,
) -> tuple[Gateway, GatewayClientConfig]:
    """Resolve board gateway and config, raising 422 when unavailable."""
    if board.gateway_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board is not attached to a gateway",
        )
    gateway = await Gateway.objects.by_id(board.gateway_id).first(session)
    if gateway is None or not gateway.url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway is not configured for this board",
        )
    return gateway, GatewayClientConfig(url=gateway.url, token=gateway.token)


async def send_gateway_agent_message(
    *,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
    deliver: bool = False,
) -> None:
    """Ensure session and dispatch a message to an agent session."""
    await ensure_session(session_key, config=config, label=agent_name)
    await send_message(message, session_key=session_key, config=config, deliver=deliver)


def resolve_trace_id(correlation_id: str | None, *, prefix: str) -> str:
    """Resolve a stable trace id from correlation id or generate a scoped fallback."""
    normalized = (correlation_id or "").strip()
    if normalized:
        return normalized
    return f"{prefix}:{uuid4().hex[:12]}"


logger = logging.getLogger(__name__)
