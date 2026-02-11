"""Approval-task link model for many-to-many approval associations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class ApprovalTaskLink(QueryModel, table=True):
    """Map an approval request to one task (many links per approval allowed)."""

    __tablename__ = "approval_task_links"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "approval_id",
            "task_id",
            name="uq_approval_task_links_approval_id_task_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    approval_id: UUID = Field(foreign_key="approvals.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
