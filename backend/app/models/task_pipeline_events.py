"""Structured task pipeline evidence events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class TaskPipelineEvent(QueryModel, table=True):
    """Append-only pipeline state evidence for a task work cycle."""

    __tablename__ = "task_pipeline_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    state: str = Field(index=True)
    source: str = Field(default="api", index=True)
    commit_sha: str | None = Field(default=None, index=True)
    artifact_hash: str | None = None
    deploy_target: str | None = None
    live_sha: str | None = None
    evidence: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
