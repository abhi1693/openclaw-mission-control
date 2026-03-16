"""Response schemas for activity events and task-comment feed items."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ActivityEventRead(SQLModel):
    """Serialized activity event payload returned by activity endpoints."""

    id: UUID
    event_type: str
    message: str | None
    agent_id: UUID | None
    task_id: UUID | None
    board_id: UUID | None = None
    route_name: str | None = None
    route_params: dict[str, str] | None = None
    created_at: datetime


class ActivityTaskCommentFeedItemRead(SQLModel):
    """Denormalized task-comment feed item enriched with task and board fields."""

    id: UUID
    created_at: datetime
    message: str | None
    agent_id: UUID | None
    agent_name: str | None = None
    agent_role: str | None = None
    task_id: UUID
    task_title: str
    board_id: UUID
    board_name: str
