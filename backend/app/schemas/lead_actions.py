"""Schemas for deterministic lead routing decisions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlmodel import Field, SQLModel


LeadNextActionName = Literal[
    "mark_done",
    "inspect_review_gates",
    "route_rework",
    "inspect_stale_in_progress",
    "route_inbox",
    "materialize_decomposition_plan",
    "cancel_orphan_child",
    "clear",
]


class LeadNextActionRead(SQLModel):
    """Single deterministic action candidate for a board lead heartbeat."""

    action_required: bool
    action: LeadNextActionName
    reason_code: str
    task_id: UUID | None = None
    task_status: str | None = None
    task_title: str | None = None
    assigned_agent_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)
