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

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class AgentHeartbeatRepairEvent(QueryModel, table=True):
    """Forensic record of a single heartbeat-watchdog repair."""

    __tablename__ = "agent_heartbeat_repair_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    prev_deadline: datetime | None = None
    last_seen_at: datetime | None = None
    wake_attempts: int = Field(default=0)
    elapsed_since_last_seen_seconds: float | None = None
    repair_reason: str = Field(index=True)
    new_deadline: datetime
    created_at: datetime = Field(default_factory=utcnow, index=True)
