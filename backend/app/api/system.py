"""System-level operator status endpoints.

Surfaces a single read-only aggregate of platform liveness signals (queue
depth, agent online/offline counts, gateway count) so a "system pulse" UI
widget can render the answer to "is anything wrong right now?" without
fanning out across multiple endpoints.

Scoped to the caller's currently active organization, mirroring how the
existing `/metrics/dashboard` endpoint is scoped.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import require_org_member
from app.core.config import settings
from app.core.time import utcnow
from app.db.session import get_session
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.schemas.system import (
    AgentCounts,
    GatewayCounts,
    QueueDepth,
    SystemStatusResponse,
)
from app.services.queue import queue_depths

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

router = APIRouter(prefix="/system", tags=["system"])

ORG_DEP = Depends(require_org_member)
SESSION_DEP = Depends(get_session)

# An agent is considered "online" when its last_seen_at falls within this
# window. The presence touch interval is 30s (see agent_auth.py), so 5 minutes
# is generous enough to cover a few missed touches without false-flagging
# briefly-quiet agents as offline.
_AGENT_ONLINE_WINDOW = timedelta(minutes=5)


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="System Status",
    description=(
        "Operator-facing aggregate status: RQ queue depth (ready + scheduled), "
        "agent online/offline counts, and gateway count, scoped to the caller's "
        "currently active organization."
    ),
)
async def get_system_status(
    org_ctx: "OrganizationContext" = ORG_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> SystemStatusResponse:
    """Return the system status payload for the caller's active organization."""
    organization_id = org_ctx.organization.id

    online_cutoff = utcnow() - _AGENT_ONLINE_WINDOW

    # ``Agent`` has no direct ``organization_id`` column — it inherits org
    # scope through its parent ``Gateway``. Match the existing pattern used
    # in tenant-scoped queries elsewhere by filtering via a gateway subquery.
    org_gateway_ids = select(Gateway.id).where(
        col(Gateway.organization_id) == organization_id,
    )

    agent_total_stmt = (
        select(func.count()).select_from(Agent).where(col(Agent.gateway_id).in_(org_gateway_ids))
    )
    agent_online_stmt = (
        select(func.count())
        .select_from(Agent)
        .where(
            col(Agent.gateway_id).in_(org_gateway_ids),
            col(Agent.last_seen_at).is_not(None),
            col(Agent.last_seen_at) >= online_cutoff,
        )
    )
    gateway_total_stmt = (
        select(func.count())
        .select_from(Gateway)
        .where(
            col(Gateway.organization_id) == organization_id,
        )
    )

    agent_total = (await session.exec(agent_total_stmt)).one()
    agent_online = (await session.exec(agent_online_stmt)).one()
    gateway_total = (await session.exec(gateway_total_stmt)).one()

    ready_depth, scheduled_depth = queue_depths(settings.rq_queue_name)

    return SystemStatusResponse(
        queue=QueueDepth(
            name=settings.rq_queue_name,
            depth=int(ready_depth),
            scheduled_depth=int(scheduled_depth),
        ),
        agents=AgentCounts(
            total=int(agent_total),
            online=int(agent_online),
            offline=int(agent_total) - int(agent_online),
        ),
        gateways=GatewayCounts(total=int(gateway_total)),
    )
