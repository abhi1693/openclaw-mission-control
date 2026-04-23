"""Schemas for Phase II Blocker CRUD (plan §I1).

See ``backend/app/models/blockers.py`` for the stored columns and
``docs/plans/2026-04-16-mc-delivery-enforcement-plan.md`` §I1 for the
invariant: no blocked work without a blocker object.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

# Mirror the ``ck_blockers_category_values`` CHECK string on the
# Blocker model. The Pydantic Literal validates API writes; the DB
# CHECK validates raw-SQL paths.
BlockerCategory = Literal["source", "deploy", "runtime", "contract", "operator"]

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class BlockerBase(SQLModel):
    """Fields shared across create/read payloads."""

    category: BlockerCategory
    owner_role: NonEmptyStr
    required_artifact: str | None = None
    target_env: str | None = None
    reopen_condition: str | None = None
    citation: str | None = None
    supersedes_blocker_id: UUID | None = None


class BlockerCreate(BlockerBase):
    """Payload for filing a new blocker against a task."""


class BlockerUpdate(SQLModel):
    """Partial update — sharpen the narrative or advance the lifecycle.

    ``acknowledged_at`` / ``resolved_at`` are server-stamped from the
    request clock; the payload only carries the intended transition so
    the endpoint owns the timestamp and the acknowledger's agent id.
    """

    required_artifact: str | None = None
    target_env: str | None = None
    reopen_condition: str | None = None
    citation: str | None = None
    status_transition: Literal["acknowledge", "resolve"] | None = None

    @model_validator(mode="after")
    def reject_noop_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class BlockerRead(BlockerBase):
    """Blocker payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    task_id: UUID
    created_by_agent_id: UUID | None
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_agent_id: UUID | None
    resolved_at: datetime | None
    # Part E.4: structured request_id extracted from 4.20+
    # PAIRING_REQUIRED remediation. Null for non-stale-agent filings.
    citation_request_id: str | None = None
