"""Schemas for board create/update/read API operations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import StrictBool, model_validator
from sqlmodel import Field, SQLModel

_ERR_GOAL_FIELDS_REQUIRED = "Confirmed goal boards require objective and success_metrics"
_ERR_GATEWAY_REQUIRED = "gateway_id is required"
_ERR_DESCRIPTION_REQUIRED = "description is required"
RUNTIME_ANNOTATION_TYPES = (datetime, UUID)

# Canonical rollout flag keys. See
# docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md §A.3
# for why this is an allowlist (F4) rather than open-ended. Unknown keys land
# in Board.rollout_flags_unknown so that operator attempts to enable new flags
# are observable without requiring a code change to unblock them.
ROLLOUT_FLAG_ALLOWLIST = frozenset(
    {
        "comment_policy_v1",
        "structured_blockers_v1",
        "operator_decisions_v1",
        "deploy_truth_v1",
        "heartbeat_watchdog_v1",
    }
)

# Phase I classifier filter modes. See amendments §1 for graduation rules.
# The Pydantic Literal enforces the allowlist at the API layer; the
# migration adds a CHECK constraint so raw-SQL paths can't smuggle in
# invalid values either.
CommentSignalFilter = Literal["off", "default_hidden", "hidden_strict"]


def partition_rollout_flags(
    flags: dict[str, bool] | None,
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Split a flag dict into (known, unknown) by the canonical allowlist.

    Type validation (reject non-bool values) is Pydantic's job via
    ``dict[str, StrictBool]`` on the ingress schemas; this helper assumes
    clean input.
    """

    if not flags:
        return {}, {}
    known: dict[str, bool] = {}
    unknown: dict[str, bool] = {}
    for key, value in flags.items():
        if key in ROLLOUT_FLAG_ALLOWLIST:
            known[key] = value
        else:
            unknown[key] = value
    return known, unknown


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
    comment_required_for_review: bool = False
    block_status_changes_with_pending_approval: bool = False
    only_lead_can_change_status: bool = False
    show_cancelled_column: bool = False
    max_agents: int = Field(default=1, ge=0)
    rollout_flags: dict[str, StrictBool] = Field(default_factory=dict)
    comment_signal_filter: CommentSignalFilter = "off"


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
    comment_required_for_review: bool | None = None
    block_status_changes_with_pending_approval: bool | None = None
    only_lead_can_change_status: bool | None = None
    show_cancelled_column: bool | None = None
    max_agents: int | None = Field(default=None, ge=0)
    rollout_flags: dict[str, StrictBool] | None = None
    comment_signal_filter: CommentSignalFilter | None = None

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
    rollout_flags_unknown: dict[str, StrictBool] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
