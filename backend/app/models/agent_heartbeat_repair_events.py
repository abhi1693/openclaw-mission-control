"""Append-only forensic log for heartbeat watchdog repairs.

Each row captures the state of an agent at the moment the watchdog found
it in ``status='online'`` with ``checkin_deadline_at IS NULL`` and repaired
the deadline. Preserving the pre-repair state makes the bug-writer path
diagnosable — without this log, repair silently erases the evidence that
the writer path dropped the deadline.

See docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md
section A.1 (failure mode F1).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, Index, Uuid
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class AgentHeartbeatRepairEvent(QueryModel, table=True):
    """Forensic record of a single heartbeat-watchdog repair."""

    __tablename__ = "agent_heartbeat_repair_events"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # Composite ``(created_at, agent_id)`` serves the windowed
        # ``GROUP BY agent_id`` query which filters ``created_at >=
        # since`` first, then aggregates. Leading with created_at lets
        # the planner do a range scan, then HashAggregate.
        Index(
            "ix_agent_heartbeat_repair_events_created_at_agent_id",
            "created_at",
            "agent_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(
        sa_column=Column(
            Uuid(),
            ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    prev_deadline: datetime | None = None
    last_seen_at: datetime | None = None
    wake_attempts: int = Field(default=0)
    elapsed_since_last_seen_seconds: float | None = None
    repair_reason: str = Field(index=True)
    new_deadline: datetime
    # created_at is not single-column-indexed — the composite above
    # covers the only access pattern (range filter + agent_id group).
    # Do not re-add ``index=True`` here; it would drift against the
    # migration which intentionally doesn't create ``ix_created_at``.
    created_at: datetime = Field(default_factory=utcnow)
    # Part E.1: raw ``models.authStatus`` snapshot captured at repair
    # time. Populated best-effort — ``None`` when the gateway doesn't
    # support the method (4.14 and earlier) or the transport degrades.
    # Operator-visible for manual correlation today; a follow-up
    # commit lands the alert-gate that suppresses "3× repair / 1h"
    # WARNs when any snapshot in the window reports provider-side
    # degradation.
    auth_status_snapshot: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
