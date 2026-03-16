"""Shared DB mutation helpers for OpenClaw agent lifecycle services."""

from __future__ import annotations

from typing import Literal

from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.time import utcnow
from app.models.agents import Agent
from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG


def ensure_heartbeat_config(agent: Agent) -> None:
    """Ensure an agent has a heartbeat_config dict populated."""

    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()


def mint_agent_token(agent: Agent) -> str:
    """Generate a new raw token and update the agent's token hash."""

    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    return raw_token


def mark_provision_requested(
    agent: Agent,
    *,
    action: str,
    status: str | None = None,
) -> None:
    """Mark an agent as pending provisioning/update."""

    ensure_heartbeat_config(agent)
    agent.provision_requested_at = utcnow()
    agent.provision_action = action
    if status is not None:
        agent.status = status
    agent.updated_at = utcnow()


def mark_provision_complete(
    agent: Agent,
    *,
    status: Literal["online", "offline", "provisioning", "updating", "deleting"] = "online",
    clear_confirm_token: bool = False,
) -> None:
    """Clear provisioning fields after a successful gateway lifecycle run."""

    if clear_confirm_token:
        agent.provision_confirm_token_hash = None
    agent.status = status
    agent.provision_requested_at = None
    agent.provision_action = None
    agent.updated_at = utcnow()
