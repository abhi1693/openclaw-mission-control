"""Schemas for board webhook configuration and payload capture endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


def _normalize_secret(v: str | None) -> str | None:
    """Normalize blank/whitespace-only secrets to None."""
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None


NormalizedSecret = Annotated[str | None, BeforeValidator(_normalize_secret)]


class BoardWebhookCreate(SQLModel):
    """Payload for creating a board webhook."""

    description: NonEmptyStr
    enabled: bool = True
    agent_id: UUID | None = None
    secret: NormalizedSecret = None


class BoardWebhookUpdate(SQLModel):
    """Payload for updating a board webhook."""

    description: NonEmptyStr | None = None
    enabled: bool | None = None
    agent_id: UUID | None = None
    secret: NormalizedSecret = None


class BoardWebhookRead(SQLModel):
    """Serialized board webhook configuration."""

    id: UUID
    board_id: UUID
    agent_id: UUID | None = None
    description: str
    enabled: bool
    has_secret: bool = False
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
