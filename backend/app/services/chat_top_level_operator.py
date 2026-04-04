"""Helpers to resolve the organization's top-level chat operator agent.

Mission Control stores chat sender/target identity using the real `agents.id`
primary key. This module uses a stable `agents.system_key` flag to locate the
correct agent id deterministically.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.gateways import Gateway

TOP_LEVEL_OPERATOR_SYSTEM_KEY = "yas_claw"


async def resolve_top_level_operator_agent_id(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> UUID:
    """Resolve the agent id for the org's top-level chat operator.

    Uses `agents.system_key` as the stable selector, but falls back to any
    `board_id is None` (gateway-main agent) if the system key is unset.
    """

    statement = (
        select(Agent.id)
        .join(Gateway, col(Agent.gateway_id) == col(Gateway.id))
        .where(col(Gateway.organization_id) == organization_id)
        .where(col(Agent.system_key) == TOP_LEVEL_OPERATOR_SYSTEM_KEY)
        .limit(1)
    )
    resolved = (await session.exec(statement)).first()
    if resolved is not None:
        return resolved

    # Fallback for environments that haven't set system keys yet.
    # "Gateway main" agents have `board_id IS NULL` in this codebase.
    fallback_statement = (
        select(Agent.id)
        .join(Gateway, col(Agent.gateway_id) == col(Gateway.id))
        .where(col(Gateway.organization_id) == organization_id)
        .where(col(Agent.board_id).is_(None))
        .limit(1)
    )
    fallback = (await session.exec(fallback_statement)).first()
    if fallback is not None:
        return fallback

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            "Top-level operator agent not found. "
            f"Set `agents.system_key='{TOP_LEVEL_OPERATOR_SYSTEM_KEY}'`."
        ),
    )

