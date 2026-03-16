"""Task/tag many-to-many link rows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class TagAssignment(QueryModel, table=True):
    """Association row mapping one task to one tag."""

    __tablename__ = "tag_assignments"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "tag_id",
            name="uq_tag_assignments_task_id_tag_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    tag_id: UUID = Field(foreign_key="tags.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
