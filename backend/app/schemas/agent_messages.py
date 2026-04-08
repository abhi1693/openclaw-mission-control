"""Schemas for inter-agent communication API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class AgentMessageCreate(SQLModel):
    """Payload for sending an inter-agent message."""

    content: NonEmptyStr
    receiver_agent_id: UUID | None = None
    task_id: UUID | None = None


class AgentMessageRead(SQLModel):
    """Serialized agent message returned from read endpoints."""

    id: UUID
    board_id: UUID
    sender_agent_id: UUID
    receiver_agent_id: UUID | None = None
    task_id: UUID | None = None
    content: str
    created_at: datetime
