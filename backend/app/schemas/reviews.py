"""Schemas for Phase II Review + ReviewBlocker endpoints (plan §I4).

§I4 makes reviews emit structured blockers, not prose. The
``ReviewCreate`` payload therefore carries the blocker descriptors
inline; the handler materialises them as ``Blocker`` rows and links
each to the new ``Review`` via ``ReviewBlocker``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from app.schemas.blockers import BlockerCategory
from app.schemas.common import NonEmptyStr, ReasonCode

ReviewVerdict = Literal["pass", "fail", "needs_changes"]

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class ReviewBlockerDescriptor(SQLModel):
    """Inline blocker spec carried on a review payload.

    Reviewers do not file blockers through ``POST /blockers`` and then
    reference them here — §I4 writes both rows in one transaction so a
    FAIL verdict cannot leave the DB in a half-blocked state.
    """

    category: BlockerCategory
    # See ``app.services.blocker_reason_codes`` for the canonical recognised registry.
    reason_code: ReasonCode = None
    owner_role: NonEmptyStr
    required_artifact: str | None = None
    target_env: str | None = None
    reopen_condition: str | None = None
    # Plan §I4 calls this "citation" on the blocker row; distinct from
    # the review-level citation below. Kept optional so the reviewer
    # can rely on the review-level narrative when per-blocker quoting
    # would be redundant.
    citation: str | None = None


class ReviewCreate(SQLModel):
    """Payload for submitting a review verdict on a task."""

    verdict: ReviewVerdict
    citation: str | None = None
    blockers: list[ReviewBlockerDescriptor] = Field(default_factory=list)

    @model_validator(mode="after")
    def fail_requires_blockers(self) -> Self:
        # §I4: "FAIL with zero blockers returns 422". The SQL-layer
        # CHECK pins the verdict vocabulary but cannot see the
        # blockers[] list, so this guard sits in Pydantic.
        if self.verdict == "fail" and not self.blockers:
            raise ValueError("verdict=fail requires at least one blocker row")
        return self


class ReviewBlockerRead(SQLModel):
    """A single blocker linked to a review, flattened for the client."""

    id: UUID
    blocker_id: UUID
    category: BlockerCategory
    # Exposes the structured reason code stamped at review-create time so
    # readers can run the same revalidation dispatch as ad-hoc blockers
    # without an extra fetch against the Blocker row.
    reason_code: str | None = None
    owner_role: str
    required_artifact: str | None
    target_env: str | None
    reopen_condition: str | None
    citation: str | None = None


class ReviewRead(SQLModel):
    """Review payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    task_id: UUID
    verdict: ReviewVerdict
    citation: str | None
    reviewer_agent_id: UUID | None
    created_at: datetime
    blockers: list[ReviewBlockerRead] = Field(default_factory=list)
