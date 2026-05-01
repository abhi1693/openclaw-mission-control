"""System status response schemas.

These power the operator-facing `GET /api/v1/system/status` endpoint, which
surfaces a single read-only aggregate of platform liveness signals: queue
depth, agent online/offline counts, and gateway count. Intended to back a
"system pulse" widget on the dashboard without forcing operators to read
multiple endpoints to assemble the same view.
"""

from __future__ import annotations

from pydantic import Field
from sqlmodel import SQLModel


class QueueDepth(SQLModel):
    """Depth signals for a single named RQ queue."""

    name: str = Field(
        description="Queue name (e.g. the configured `RQ_QUEUE_NAME`).",
        examples=["default"],
    )
    depth: int = Field(
        description="Number of tasks currently waiting in the ready queue.",
        examples=[0],
    )
    scheduled_depth: int = Field(
        description="Number of tasks parked in the delayed/scheduled set.",
        examples=[0],
    )


class AgentCounts(SQLModel):
    """Aggregate counts of agents in this Mission Control deploy."""

    total: int = Field(
        description="Total agents across every accessible organization.",
        examples=[23],
    )
    online: int = Field(
        description=(
            "Agents whose `last_seen_at` is within the configured online window "
            "(default: last 5 minutes)."
        ),
        examples=[1],
    )
    offline: int = Field(
        description="Agents whose `last_seen_at` is older than the online window, or NULL.",
        examples=[22],
    )


class GatewayCounts(SQLModel):
    """Aggregate counts of gateways."""

    total: int = Field(
        description="Total gateways registered across every accessible organization.",
        examples=[1],
    )


class SystemStatusResponse(SQLModel):
    """Aggregate operator status payload returned by `GET /system/status`."""

    queue: QueueDepth = Field(
        description="RQ queue depth for the configured `RQ_QUEUE_NAME`.",
    )
    agents: AgentCounts = Field(
        description="Agent counts across the operator's accessible organizations.",
    )
    gateways: GatewayCounts = Field(
        description="Gateway counts across the operator's accessible organizations.",
    )
