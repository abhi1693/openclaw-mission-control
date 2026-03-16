"""Deterministic session-key helpers for OpenClaw agents.

Session keys are part of Mission Control's contract with the OpenClaw gateway.
Centralize the string formats here to avoid drift across provisioning, DB workflows,
and API-facing services.
"""

from __future__ import annotations

from uuid import UUID

from app.services.openclaw.constants import AGENT_SESSION_PREFIX
from app.services.openclaw.shared import GatewayAgentIdentity


def gateway_main_session_key(gateway_id: UUID) -> str:
    """Return the deterministic session key for a gateway-main agent."""
    return GatewayAgentIdentity.session_key_for_id(gateway_id)


def board_lead_session_key(board_id: UUID) -> str:
    """Return the deterministic session key for a board lead agent."""
    return f"{AGENT_SESSION_PREFIX}:lead-{board_id}:main"


def board_agent_session_key(agent_id: UUID) -> str:
    """Return the deterministic session key for a non-lead, board-scoped agent."""
    return f"{AGENT_SESSION_PREFIX}:mc-{agent_id}:main"


def board_scoped_session_key(
    *,
    agent_id: UUID,
    board_id: UUID,
    is_board_lead: bool,
) -> str:
    """Return the deterministic session key for a board-scoped agent."""
    if is_board_lead:
        return board_lead_session_key(board_id)
    return board_agent_session_key(agent_id)
