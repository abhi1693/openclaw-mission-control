"""Persisted webhook payloads received for board webhooks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class BoardWebhookPayload(QueryModel, table=True):
    """Captured inbound webhook payload with request metadata."""

    __tablename__ = "board_webhook_payloads"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    webhook_id: UUID = Field(foreign_key="board_webhooks.id", index=True)
    payload: dict[str, object] | list[object] | str | int | float | bool | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    headers: dict[str, str] | None = Field(default=None, sa_column=Column(JSON))
    source_ip: str | None = None
    content_type: str | None = None
    received_at: datetime = Field(default_factory=utcnow, index=True)
