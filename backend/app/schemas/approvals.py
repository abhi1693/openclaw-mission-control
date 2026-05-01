"""Schemas for approval create/update/read API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import Field, SQLModel

ApprovalStatus = Literal["pending", "approved", "rejected"]
STATUS_REQUIRED_ERROR = "status is required"
LEAD_REASONING_REQUIRED_ERROR = "lead reasoning is required"
RUNTIME_ANNOTATION_TYPES = (datetime, UUID)

# Canonical set of ``action_type`` values that mean "approve to move
# this task to ``done``". Multiple aliases exist because Supervisor
# models historically emit different strings — keep all aliases here
# so every gate (validation, lead approval-state lookup,
# pending-approval auto-reject on cancel) recognises the same set.
# Adding a new alias requires updating ONLY this constant.
DONE_APPROVAL_ACTION_TYPES: tuple[str, ...] = (
    "move_to_done",
    "mark_done",
    "task_done",
    "move_task_to_done",
    "mark_task_done",
)


class ApprovalBase(SQLModel):
    """Shared approval fields used across create/read payloads."""

    action_type: str
    task_id: UUID | None = None
    task_ids: list[UUID] = Field(default_factory=list)
    payload: dict[str, object] | None = None
    confidence: float = Field(ge=0, le=100)
    rubric_scores: dict[str, int] | None = None
    status: ApprovalStatus = "pending"

    @model_validator(mode="after")
    def normalize_task_links(self) -> Self:
        """Keep task identifiers deduplicated and task_id aligned with task_ids."""
        deduped: list[UUID] = []
        seen: set[UUID] = set()
        if self.task_id is not None:
            deduped.append(self.task_id)
            seen.add(self.task_id)
        for task_id in self.task_ids:
            if task_id in seen:
                continue
            seen.add(task_id)
            deduped.append(task_id)
        self.task_ids = deduped
        self.task_id = deduped[0] if deduped else None
        return self


class ApprovalCreate(ApprovalBase):
    """Payload for creating a new approval request."""

    agent_id: UUID | None = None
    lead_reasoning: str | None = None

    @model_validator(mode="after")
    def validate_lead_reasoning(self) -> Self:
        """Ensure each approval request includes explicit lead reasoning."""
        payload = self.payload
        if isinstance(payload, dict):
            reason = payload.get("reason")
            if isinstance(reason, str) and reason.strip():
                return self
            decision = payload.get("decision")
            if isinstance(decision, dict):
                nested_reason = decision.get("reason")
                if isinstance(nested_reason, str) and nested_reason.strip():
                    return self
        lead_reasoning = self.lead_reasoning
        if isinstance(lead_reasoning, str) and lead_reasoning.strip():
            self.payload = {
                **(payload if isinstance(payload, dict) else {}),
                "reason": lead_reasoning.strip(),
            }
            return self
        raise ValueError(LEAD_REASONING_REQUIRED_ERROR)


class ApprovalUpdate(SQLModel):
    """Payload for mutating approval status."""

    status: ApprovalStatus | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Ensure explicitly provided `status` is not null."""
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(STATUS_REQUIRED_ERROR)
        return self


class ApprovalRead(ApprovalBase):
    """Approval payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    task_titles: list[str] = Field(default_factory=list)
    agent_id: UUID | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ApprovalUnblock(SQLModel):
    """Payload for clearing a rejection loop on a task/approval.

    An authenticated human user or board lead agent calls this endpoint
    to explicitly cut through the ``_ensure_no_rejection_loop`` guard
    when they have reviewed the situation out-of-band. The reason is
    recorded on the resulting ``approval_history`` row so the unblock
    is auditable.
    """

    reason: str = Field(min_length=1, max_length=2000)
