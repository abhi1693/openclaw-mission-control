"""Schemas for board create/update/read API operations."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import SQLModel

_ERR_GOAL_FIELDS_REQUIRED = "Confirmed goal boards require objective and success_metrics"
_ERR_GATEWAY_REQUIRED = "gateway_id is required"
_ERR_DESCRIPTION_REQUIRED = "description is required"
RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class BoardBase(SQLModel):
    """Shared board fields used across create and read payloads."""

    name: str
    slug: str
    description: str
    gateway_id: UUID | None = None
    board_group_id: UUID | None = None
    board_type: str = "goal"
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None
    goal_confirmed: bool = False
    goal_source: str | None = None
    require_approval_for_done: bool = True
    require_review_before_done: bool = False
    block_status_changes_with_pending_approval: bool = False
    only_lead_can_change_status: bool = False


class BoardCreate(BoardBase):
    """Payload for creating a board."""

    gateway_id: UUID | None = None

    @model_validator(mode="after")
    def validate_goal_fields(self) -> Self:
        """Require gateway and goal details when creating a confirmed goal board."""
        description = self.description.strip()
        if not description:
            raise ValueError(_ERR_DESCRIPTION_REQUIRED)
        self.description = description
        if self.gateway_id is None:
            raise ValueError(_ERR_GATEWAY_REQUIRED)
        if (
            self.board_type == "goal"
            and self.goal_confirmed
            and (not self.objective or not self.success_metrics)
        ):
            raise ValueError(_ERR_GOAL_FIELDS_REQUIRED)
        return self


class BoardUpdate(SQLModel):
    """Payload for partial board updates."""

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    gateway_id: UUID | None = None
    board_group_id: UUID | None = None
    board_type: str | None = None
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None
    goal_confirmed: bool | None = None
    goal_source: str | None = None
    require_approval_for_done: bool | None = None
    require_review_before_done: bool | None = None
    block_status_changes_with_pending_approval: bool | None = None
    only_lead_can_change_status: bool | None = None

    @model_validator(mode="after")
    def validate_gateway_id(self) -> Self:
        """Reject explicit null gateway IDs in patch payloads."""
        # Treat explicit null like "unset" is invalid for patch updates.
        if "gateway_id" in self.model_fields_set and self.gateway_id is None:
            raise ValueError(_ERR_GATEWAY_REQUIRED)
        if "description" in self.model_fields_set:
            if self.description is None:
                raise ValueError(_ERR_DESCRIPTION_REQUIRED)
            description = self.description.strip()
            if not description:
                raise ValueError(_ERR_DESCRIPTION_REQUIRED)
            self.description = description
        return self


class BoardRead(BoardBase):
    """Board payload returned from read endpoints."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
