"""Sprint retrospective entry model."""

# NOTE: `from __future__ import annotations` is intentionally absent.
# The field name `date` conflicts with `datetime.date` under deferred-annotation
# evaluation. We import `date as Date` to avoid the name-collision and keep the
# model compatible with both Pydantic v2 and SQLModel 0.0.32.

from datetime import date as Date
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel


class RetroEntry(QueryModel, table=True):
    """A single retrospective item linked to a board and sprint."""

    __tablename__ = "retro_entries"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    sprint_id: int = Field(index=True)
    category: str = Field(index=True)
    content: str
    author: str = Field(index=True)
    date: Date
    status: str = Field(default="active", index=True)
    priority: Optional[str] = None
    is_action_item: bool = Field(default=False)
    recurrence: bool = Field(default=False)
    layer: Optional[str] = None
    nda_ref: Optional[str] = None
    resolved_sprint: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
