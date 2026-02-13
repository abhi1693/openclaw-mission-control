"""Approval model storing pending and resolved approval actions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Float
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Approval(QueryModel, table=True):
    """Approval request and decision metadata for gated operations."""

    __tablename__ = "approvals"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    action_type: str
    payload: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    confidence: float = Field(sa_column=Column(Float, nullable=False))
    rubric_scores: dict[str, int] | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
