"""Schemas for task pipeline event APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import field_validator
from sqlmodel import Field, SQLModel

PipelineState = Literal[
    "code_changed",
    "committed",
    "built",
    "deployed",
    "live_build_verified",
    "runtime_verified",
    "qa_ready",
]


class TaskPipelineEventCreate(SQLModel):
    """Payload for recording one structured pipeline event."""

    state: PipelineState
    source: str = "api"
    commit_sha: str | None = None
    artifact_hash: str | None = None
    deploy_target: str | None = None
    live_sha: str | None = None
    evidence: dict[str, object] | None = Field(default=None)

    @field_validator(
        "source",
        "commit_sha",
        "artifact_hash",
        "deploy_target",
        "live_sha",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class TaskPipelineEventRead(SQLModel):
    """Serialized pipeline event."""

    id: UUID
    board_id: UUID
    task_id: UUID
    agent_id: UUID | None
    state: str
    source: str
    commit_sha: str | None
    artifact_hash: str | None
    deploy_target: str | None
    live_sha: str | None
    evidence: dict[str, object] | None
    created_at: datetime


class TaskPipelineStateRead(SQLModel):
    """Current structured pipeline readiness for a task."""

    task_id: UUID
    required_states: list[str]
    present_states: list[str]
    missing_states: list[str]
    ready: bool
    events: list[TaskPipelineEventRead]
