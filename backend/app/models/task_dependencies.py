"""Task dependency edge model for board-local dependency graphs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class TaskDependency(TenantScoped, table=True):
    """Directed dependency edge between two tasks in the same board."""

    __tablename__ = "task_dependencies"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "depends_on_task_id",
            name="uq_task_dependencies_task_id_depends_on_task_id",
        ),
        CheckConstraint(
            "task_id <> depends_on_task_id",
            name="ck_task_dependencies_no_self",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    depends_on_task_id: UUID = Field(foreign_key="tasks.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
