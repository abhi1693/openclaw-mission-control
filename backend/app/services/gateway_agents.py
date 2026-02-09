"""Helpers for dedicated gateway-scoped agent identity/session keys."""

from __future__ import annotations

from uuid import UUID

from app.models.gateways import Gateway

_GATEWAY_AGENT_PREFIX = "agent:gateway-"
_GATEWAY_AGENT_SUFFIX = ":main"


def gateway_agent_session_key_for_id(gateway_id: UUID) -> str:
    """Return the dedicated Mission Control gateway-agent session key for an id."""
    return f"{_GATEWAY_AGENT_PREFIX}{gateway_id}{_GATEWAY_AGENT_SUFFIX}"


def gateway_agent_session_key(gateway: Gateway) -> str:
    """Return the dedicated Mission Control gateway-agent session key."""
    return gateway_agent_session_key_for_id(gateway.id)


def parse_gateway_agent_session_key(session_key: str | None) -> UUID | None:
    """Parse a gateway id from a dedicated gateway-agent session key."""
    value = (session_key or "").strip()
    if not (value.startswith(_GATEWAY_AGENT_PREFIX) and value.endswith(_GATEWAY_AGENT_SUFFIX)):
        return None
    gateway_id = value[len(_GATEWAY_AGENT_PREFIX) : -len(_GATEWAY_AGENT_SUFFIX)]
    if not gateway_id:
        return None
    try:
        return UUID(gateway_id)
    except ValueError:
        return None
