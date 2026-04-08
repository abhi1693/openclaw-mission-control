"""Agent message model for inter-agent communications."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Text
from sqlmodel import Column, Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class AgentMessage(QueryModel, table=True):
    """Persisted message exchanged between agents within a board."""

    __tablename__ = "agent_messages"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    sender_agent_id: UUID = Field(foreign_key="agents.id", index=True)
    receiver_agent_id: UUID | None = Field(
        default=None, foreign_key="agents.id", index=True
    )
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
