"""Schemas for applying heartbeat settings to board-group agents."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (UUID,)


class BoardGroupHeartbeatApply(SQLModel):
    """Request payload for heartbeat policy updates."""

    # Heartbeat cadence string understood by the OpenClaw gateway
    # (e.g. "2m", "10m", "30m").
    every: str
    include_board_leads: bool = False


class BoardGroupHeartbeatApplyResult(SQLModel):
    """Result payload describing agents updated by a heartbeat request."""

    board_group_id: UUID
    requested: dict[str, Any]
    updated_agent_ids: list[UUID]
    failed_agent_ids: list[UUID]
