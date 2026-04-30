"""Health and readiness probe response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel


class HealthStatusResponse(SQLModel):
    """Standard payload for service liveness/readiness checks."""

    ok: bool = Field(
        description="Indicates whether the probe check succeeded.",
        examples=[True],
    )


class ReadinessStatusResponse(SQLModel):
    """Readiness payload reporting per-dependency probe results.

    Returned with HTTP 200 when every dependency check is healthy and HTTP 503
    when any dependency is unreachable. The `checks` map contains one entry per
    probed dependency with value "ok" or "fail".
    """

    ok: bool = Field(
        description="True when every dependency check succeeded.",
        examples=[True],
    )
    checks: dict[str, str] = Field(
        default_factory=dict,
        description='Per-dependency probe results, keyed by dependency name (e.g. "db", "redis").',
        examples=[{"db": "ok", "redis": "ok"}],
    )


class AgentHealthStatusResponse(HealthStatusResponse):
    """Agent-authenticated liveness payload for agent route probes."""

    agent_id: UUID = Field(
        description="Authenticated agent id derived from `X-Agent-Token`.",
        examples=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
    )
    board_id: UUID | None = Field(
        default=None,
        description="Board scope for the authenticated agent, when applicable.",
        examples=["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"],
    )
    gateway_id: UUID = Field(
        description="Gateway owning the authenticated agent.",
        examples=["cccccccc-cccc-cccc-cccc-cccccccccccc"],
    )
    status: str = Field(
        description="Current persisted lifecycle status for the authenticated agent.",
        examples=["online", "healthy", "updating"],
    )
    is_board_lead: bool = Field(
        description="Whether the authenticated agent is the board lead.",
        examples=[False],
    )
