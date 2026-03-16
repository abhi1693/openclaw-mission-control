"""Board-group scoped memory entries for shared context."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class BoardGroupMemory(QueryModel, table=True):
    """Persisted memory items associated with a board group."""

    __tablename__ = "board_group_memory"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_group_id: UUID = Field(foreign_key="board_groups.id", index=True)
    content: str
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    is_chat: bool = Field(default=False, index=True)
    source: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
