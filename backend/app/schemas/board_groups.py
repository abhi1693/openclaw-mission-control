"""Schemas for board-group create/update/read API operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class BoardGroupBase(SQLModel):
    """Shared board-group fields for create/read operations."""

    name: str
    slug: str
    description: str | None = None


class BoardGroupCreate(BoardGroupBase):
    """Payload for creating a board group."""


class BoardGroupUpdate(SQLModel):
    """Payload for partial board-group updates."""

    name: str | None = None
    slug: str | None = None
    description: str | None = None


class BoardGroupRead(BoardGroupBase):
    """Board-group payload returned from read endpoints."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
