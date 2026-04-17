"""Append-only shadow metric events for Phase 0 observability.

Each row captures a classifier or gate-instrumentation signal *without*
mutating caller-visible behavior. Phase 0 uses this table to size the
pathology (how often ack-only comments fire, how often actionability
violations would have rejected) before Phase I turns any of it into
hard enforcement.

See ``docs/plans/2026-04-16-mc-delivery-enforcement-plan.md`` §Phase 0
and the amendments doc §A.2, §A.4, §A.5.

Retention: 90 days per amendment §A.4. Enforcement is a downstream job
(not yet implemented); ``created_at`` has an index so a purge query can
scan efficiently when that lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, ForeignKey, Uuid
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class ShadowMetricEvent(QueryModel, table=True):
    """One observability signal emitted by a shadow-mode classifier or hook."""

    __tablename__ = "shadow_metric_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Examples: "comment.ack_only_candidate", "comment.near_duplicate_candidate",
    # "task.actionability_violation_candidate". See app.services.shadow_metrics
    # for the canonical constants.
    event_type: str = Field(index=True)
    # ON DELETE CASCADE so shadow rows track their subject: when the
    # task/agent/board is deleted, the observability history for it is
    # no longer meaningful (source_event_id would dangle anyway since
    # task deletion removes the underlying activity_events rows).
    task_id: UUID | None = Field(
        default=None,
        sa_column=Column(Uuid(), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True),
    )
    agent_id: UUID | None = Field(
        default=None,
        sa_column=Column(Uuid(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
    )
    board_id: UUID | None = Field(
        default=None,
        sa_column=Column(Uuid(), ForeignKey("boards.id", ondelete="CASCADE"), nullable=True),
    )
    # Optional pointer to the activity event that triggered this metric.
    # Not a FK — activity rows may be pruned independently.
    source_event_id: UUID | None = Field(default=None)
    # Classifier / instrumentation context (e.g., packet_type, jaccard,
    # rework_count). Shape varies by event_type; downstream readers
    # key off the event_type value to know which fields to expect.
    classifier_metadata: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
