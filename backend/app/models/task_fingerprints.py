"""Task fingerprint model for duplicate/task-linking operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class TaskFingerprint(QueryModel, table=True):
    """Hashed task-content fingerprint associated with a board and task."""

    __tablename__ = "task_fingerprints"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    fingerprint_hash: str = Field(index=True)
    task_id: UUID = Field(foreign_key="tasks.id")
    created_at: datetime = Field(default_factory=utcnow)
