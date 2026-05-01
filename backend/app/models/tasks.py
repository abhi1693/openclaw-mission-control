"""Task model representing board work items and execution metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Task(TenantScoped, table=True):
    """Board-scoped task entity with ownership, status, and timing fields."""

    __tablename__ = "tasks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source_memory_id", name="uq_tasks_source_memory_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True)

    title: str
    description: str | None = None
    status: str = Field(default="inbox", index=True)
    priority: str = Field(default="medium", index=True)
    due_at: datetime | None = None
    in_progress_at: datetime | None = None
    previous_in_progress_at: datetime | None = None
    rework_started_at: datetime | None = Field(default=None, index=True)
    cancelled_at: datetime | None = None
    review_packet_type: str | None = None
    validation_target: str | None = None
    validation_target_kind: str | None = None
    validation_target_scope: str | None = None
    # Phase V §I8 deploy-truth metadata. The packet SHA is what the
    # reviewer claims is (or was) deployed; the build SHA is the
    # downstream artefact tag when the target produces one distinct
    # from the source commit. ``supports_build_metadata`` is the
    # target capability flag — True means the target exposes a
    # ``GET /__build`` endpoint and SHA comparison is mandatory;
    # False means the target is deploy-blind and validation is
    # marked degraded; None means unknown (pre-migration rows or
    # targets operators haven't classified yet).
    packet_commit_sha: str | None = None
    rework_entry_commit_sha: str | None = None
    packet_build_sha: str | None = None
    supports_build_metadata: bool | None = None
    operator_decision_required: bool = Field(default=False, index=True)
    operator_decision_summary: str | None = None
    source_memory_id: UUID | None = Field(
        default=None,
        foreign_key="board_memory.id",
        index=True,
    )
    # Phase V: explicit parent/child link for decomposition cascade.
    # Set when a subtask is created from a parent's decomposition plan
    # (see ``lead-inbox-routing`` Umbrella Lifecycle). Distinct from
    # ``TaskDependency`` (ordering) — children point at the umbrella,
    # not at sibling prereqs.
    parent_task_id: UUID | None = Field(
        default=None,
        foreign_key="tasks.id",
        index=True,
    )

    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    assigned_agent_id: UUID | None = Field(
        default=None,
        foreign_key="agents.id",
        index=True,
    )
    auto_created: bool = Field(default=False)
    auto_reason: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
