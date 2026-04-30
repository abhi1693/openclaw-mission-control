"""Schemas for Phase III OperatorDecision CRUD (plan §I3).

Lifecycle: ``pending`` → ``resolved`` (with ``resolved_value``) or
``cancelled``. Forward-only — a resolved decision never reopens; a
superseding decision is a new row that re-links the same tasks.

See ``backend/app/models/operator_decisions.py`` for stored columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr, ReasonCode

OperatorDecisionStatus = Literal["pending", "resolved", "cancelled"]

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class OperatorDecisionCreate(SQLModel):
    """Payload for escalating a new operator decision."""

    question: NonEmptyStr
    owner_user_id: UUID | None = None
    unblock_rule: str | None = None
    # See ``app.services.blocker_reason_codes`` for the canonical recognised registry.
    reason_code: ReasonCode = None
    dependent_task_ids: list[UUID] = Field(default_factory=list)


class OperatorDecisionUpdate(SQLModel):
    """Partial update — advance lifecycle or sharpen metadata.

    ``resolved_at`` is server-stamped from the request clock when
    ``status_transition="resolve"`` fires; the payload only carries
    the intent.
    """

    owner_user_id: UUID | None = None
    unblock_rule: str | None = None
    reason_code: ReasonCode = None
    resolved_value: str | None = None
    status_transition: Literal["resolve", "cancel"] | None = None

    @field_validator("resolved_value", "unblock_rule", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        """Blank / whitespace-only strings collapse to None so the
        ``resolve_requires_value`` guard below sees a truthful null
        instead of accepting an effectively-empty answer."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def reject_noop_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self

    @model_validator(mode="after")
    def resolve_requires_value(self) -> Self:
        # ``cancel`` is acceptable without a resolved_value — it
        # communicates "decision no longer relevant." ``resolve`` must
        # carry a truthy answer so downstream consumers can act on it.
        # Checking ``self.resolved_value is None`` as well as
        # model_fields_set catches callers who pass explicit
        # ``resolved_value: null`` alongside ``status_transition:
        # "resolve"`` — which would otherwise register in the set and
        # pass the guard while persisting a null answer.
        if self.status_transition == "resolve" and self.resolved_value is None:
            raise ValueError(
                "status_transition='resolve' requires a non-null resolved_value"
            )
        return self


class OperatorDecisionRead(SQLModel):
    """OperatorDecision payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    question: str
    owner_user_id: UUID | None
    unblock_rule: str | None
    reason_code: str | None = None
    status: OperatorDecisionStatus
    resolved_value: str | None
    created_by_agent_id: UUID | None
    created_at: datetime
    resolved_at: datetime | None
    dependent_task_ids: list[UUID] = Field(default_factory=list)
