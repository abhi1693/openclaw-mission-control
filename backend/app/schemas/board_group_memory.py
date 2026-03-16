"""Schemas for board-group memory create/read API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class BoardGroupMemoryCreate(SQLModel):
    """Payload for creating a board-group memory entry."""

    # For writes, reject blank/whitespace-only content.
    content: NonEmptyStr
    tags: list[str] | None = None
    source: str | None = None


class BoardGroupMemoryRead(SQLModel):
    """Serialized board-group memory entry returned from read endpoints."""

    id: UUID
    board_group_id: UUID
    # For reads, allow legacy rows that may have empty content
    # (avoid response validation 500s).
    content: str
    tags: list[str] | None = None
    source: str | None = None
    is_chat: bool = False
    created_at: datetime
