"""Schemas for board webhook configuration and payload capture endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)

# RFC 7230 token characters: visible ASCII except delimiters.
_HTTP_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _normalize_secret(v: str | None) -> str | None:
    """Normalize blank/whitespace-only secrets to None."""
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None


def _normalize_signature_header(v: str | None) -> str | None:
    """Normalize and validate signature_header as a valid HTTP header name."""
    if v is None:
        return None
    stripped = v.strip()
    if not stripped:
        return None
    if not _HTTP_TOKEN_RE.match(stripped):
        msg = "signature_header must be a valid HTTP header name (ASCII token characters only)"
        raise ValueError(msg)
    return stripped


NormalizedSecret = Annotated[str | None, BeforeValidator(_normalize_secret)]
NormalizedSignatureHeader = Annotated[str | None, BeforeValidator(_normalize_signature_header)]


class BoardWebhookCreate(SQLModel):
    """Payload for creating a board webhook."""

    description: NonEmptyStr
    enabled: bool = True
    agent_id: UUID | None = None
    secret: NormalizedSecret = None
    signature_header: NormalizedSignatureHeader = None


class BoardWebhookUpdate(SQLModel):
    """Payload for updating a board webhook."""

    description: NonEmptyStr | None = None
    enabled: bool | None = None
    agent_id: UUID | None = None
    secret: NormalizedSecret = None
    signature_header: NormalizedSignatureHeader = None


class BoardWebhookRead(SQLModel):
    """Serialized board webhook configuration."""

    id: UUID
    board_id: UUID
    agent_id: UUID | None = None
    description: str
    enabled: bool
    has_secret: bool = False
    signature_header: str | None = None
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
