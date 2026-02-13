"""Schemas for board webhook configuration and payload capture endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class BoardWebhookCreate(SQLModel):
    """Payload for creating a board webhook."""

    description: NonEmptyStr
    enabled: bool = True


class BoardWebhookUpdate(SQLModel):
    """Payload for updating a board webhook."""

    description: NonEmptyStr | None = None
    enabled: bool | None = None


class BoardWebhookRead(SQLModel):
    """Serialized board webhook configuration."""

    id: UUID
    board_id: UUID
    description: str
    enabled: bool
    endpoint_path: str
    endpoint_url: str | None = None
    created_at: datetime
    updated_at: datetime


class BoardWebhookPayloadRead(SQLModel):
    """Serialized stored webhook payload."""

    id: UUID
    board_id: UUID
    webhook_id: UUID
    payload: dict[str, object] | list[object] | str | int | float | bool | None = None
    headers: dict[str, str] | None = None
    source_ip: str | None = None
    content_type: str | None = None
    received_at: datetime


class BoardWebhookIngestResponse(SQLModel):
    """Response payload for inbound webhook ingestion."""

    ok: bool = True
    board_id: UUID
    webhook_id: UUID
    payload_id: UUID
