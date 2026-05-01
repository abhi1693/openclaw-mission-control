"""Schemas for structured task review verdict APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import field_validator
from sqlmodel import Field, SQLModel

from app.schemas.task_pipeline_events import TaskPipelineEventRead

ReviewerRole = Literal["architect", "qa_unit", "qa_e2e", "devops", "lead"]
ReviewVerdict = Literal["pass", "fail", "inconclusive", "infra_blocked"]


class TaskReviewEventCreate(SQLModel):
    """Payload for recording one structured review verdict."""

    reviewer_role: ReviewerRole
    verdict: ReviewVerdict
    evidence_type: str | None = None
    target: str | None = None
    build_hash: str | None = None
    source_commit: str | None = None
    blocking_owner: str | None = None
    suggested_routing: str | None = None
    evidence: dict[str, object] | None = Field(default=None)

    @field_validator(
        "evidence_type",
        "target",
        "build_hash",
        "source_commit",
        "blocking_owner",
        "suggested_routing",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class TaskReviewEventRead(SQLModel):
    """Serialized structured review verdict event."""

    id: UUID
    board_id: UUID
    task_id: UUID
    agent_id: UUID | None
    reviewer_role: str
    verdict: str
    evidence_type: str | None
    target: str | None
    build_hash: str | None
    source_commit: str | None
    blocking_owner: str | None
    suggested_routing: str | None
    evidence: dict[str, object] | None
    created_at: datetime


class TaskReviewReadinessRead(SQLModel):
    """Current structured review readiness for a task."""

    task_id: UUID
    review_packet_type: str | None
    required_roles: list[str]
    present_roles: list[str]
    missing_roles: list[str]
    blocking_roles: list[str]
    artifact_issues: list[str] = Field(default_factory=list)
    declared_child_task_ids: list[UUID] = Field(default_factory=list)
    missing_child_task_ids: list[UUID] = Field(default_factory=list)
    ready: bool
    events: list[TaskReviewEventRead]
    # Most recent ``model_fallback`` pipeline event for this task's current
    # cycle, if any. Surfaced inline so reviewers see WHICH model actually
    # produced the packet (after any fallback chain) without paging through
    # pipeline events. Informational — does NOT affect ``ready``; fallback
    # events are excluded from readiness gates by design.
    latest_fallback_step: TaskPipelineEventRead | None = None
