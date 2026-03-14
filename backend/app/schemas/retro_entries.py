"""Schemas for retro entry CRUD API payloads."""

# NOTE: `from __future__ import annotations` is intentionally absent.
# The field name `date` shadows `datetime.date` under deferred-annotation
# evaluation; Python 3.12 evaluates `| None` natively so the import is
# unnecessary. All nullable `date` fields use `Optional[Date]` to avoid
# the name-collision when Pydantic resolves annotations via get_type_hints().

from datetime import date as Date
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, Date)


class RetroEntryCreate(SQLModel):
    """Payload for creating a retro entry."""

    sprint_id: int
    category: str
    content: str
    author: str
    date: Date
    status: str = "active"
    priority: Optional[str] = None
    is_action_item: bool = False
    recurrence: bool = False
    layer: Optional[str] = None
    nda_ref: Optional[str] = None
    resolved_sprint: Optional[int] = None


class RetroEntryUpdate(SQLModel):
    """Payload for partial retro entry updates."""

    sprint_id: Optional[int] = None
    category: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    date: Optional[Date] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    is_action_item: Optional[bool] = None
    recurrence: Optional[bool] = None
    layer: Optional[str] = None
    nda_ref: Optional[str] = None
    resolved_sprint: Optional[int] = None


class RetroEntryRead(SQLModel):
    """Serialized retro entry returned from read endpoints."""

    id: UUID
    board_id: UUID
    sprint_id: int
    category: str
    content: str
    author: str
    date: Date
    status: str
    priority: Optional[str] = None
    is_action_item: bool
    recurrence: bool
    layer: Optional[str] = None
    nda_ref: Optional[str] = None
    resolved_sprint: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class RetroStatItem(SQLModel):
    """Single aggregated row returned by the stats endpoint."""

    sprint_id: int
    category: str
    count: int
