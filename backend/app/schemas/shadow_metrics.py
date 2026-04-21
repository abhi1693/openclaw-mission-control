"""Read schemas for the shadow_metric_events table.

Used by ``GET /api/v1/metrics/shadow`` (operator-scope) to expose
Phase 0 observability signals. See
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
§A.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import Field, SQLModel


class ShadowMetricEventRead(SQLModel):
    """One row from ``shadow_metric_events`` as returned by the API."""

    id: UUID
    event_type: str
    task_id: UUID | None = None
    agent_id: UUID | None = None
    board_id: UUID | None = None
    source_event_id: UUID | None = None
    classifier_metadata: dict[str, Any] | None = Field(default=None)
    created_at: datetime
