"""Approval policy execution logic for automatic or manual approval handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.models.agents import APPROVAL_POLICY_MODE_IMMEDIATE, get_approval_policy
from app.services.openclaw.gateway_resolver import gateway_client_config
from app.services.openclaw.gateway_rpc import resolve_approval

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.gateways import Gateway

logger = get_logger(__name__)


async def apply_approval_policy(
    agent: Agent,
    gateway: Gateway,
    approval_request: dict[str, Any],
) -> bool:
    """Apply the agent's approval policy to an approval request.

    Args:
        agent: The agent whose policy to apply.
        gateway: The gateway to use for RPC calls.
        approval_request: The approval request event payload from the gateway.

    Returns:
        True if auto-approved (immediate policy), False if requires manual review.
    """
    policy = get_approval_policy(agent)
    logger.info(
        "gateway.listener.apply_policy agent_id=%s policy=%s",
        agent.id,
        policy,
    )
    if policy.get("mode") == APPROVAL_POLICY_MODE_IMMEDIATE:
        await _auto_resolve_approval(agent, gateway, approval_request)
        return True
    return False


async def _auto_resolve_approval(
    agent: Agent,
    gateway: Gateway,
    approval_request: dict[str, Any],
) -> None:
    """Automatically approve an approval request by calling exec.approval.resolve."""
    config = gateway_client_config(gateway)
    approval_id = approval_request.get("id")
    if not approval_id:
        logger.warning(
            "gateway.listener.auto_resolve.no_approval_id agent_id=%s",
            agent.id,
        )
        return
    try:
        await resolve_approval(
            approval_id=str(approval_id),
            approved=True,
            config=config,
        )
        logger.info(
            "gateway.listener.auto_resolve.success agent_id=%s approval_id=%s",
            agent.id,
            approval_id,
        )
    except Exception:
        logger.exception(
            "gateway.listener.auto_resolve.failed agent_id=%s approval_id=%s",
            agent.id,
            approval_id,
        )
