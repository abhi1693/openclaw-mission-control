"""Shared OpenClaw lifecycle primitives."""

from __future__ import annotations

from uuid import UUID

from app.models.gateways import Gateway
from app.services.openclaw.constants import (
    _GATEWAY_AGENT_PREFIX,
    _GATEWAY_AGENT_SUFFIX,
    _GATEWAY_OPENCLAW_AGENT_PREFIX,
)


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
