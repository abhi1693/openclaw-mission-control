"""Review + ReviewBlocker sidecar models (plan §I4).

Phase II §I4: reviews emit structured blockers, not prose. A
``Review`` captures the verdict the reviewer reached on a task; if the
verdict is ``fail``, the review MUST link at least one ``Blocker`` row
via the ``review_blockers`` join table. The routing logic downstream
reads from those rows rather than parsing the review's free-text
citation, which is where Phase 2's routing drift originated.

Creating the full ``Blocker`` row lives in ``blockers.py``; this file
is the review side of the sidecar pair.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Review(TenantScoped, table=True):
    """Structured review verdict on a task."""

    __tablename__ = "reviews"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'fail', 'needs_changes')",
            name="ck_reviews_verdict_values",
        ),
        # list_task_reviews orders newest-first under a task_id
        # filter; a composite keeps that scan index-only instead of
        # a filesort when a task accumulates rework-cycle reviews.
        Index(
            "ix_reviews_task_id_created_at",
            "task_id",
            "created_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # board_id is carried for tenant scope (authz + cascade) even
    # though most reads reach it via task_id → tasks.board_id.
    board_id: UUID = Field(foreign_key="boards.id")
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    verdict: str
    # Reviewer's narrative. Routing data lives in the linked blocker
    # rows; this is plain text so the Supervisor can render it inline
    # without schema churn.
    citation: str | None = None
    reviewer_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ReviewBlocker(TenantScoped, table=True):
    """Join row linking a Review to a Blocker.

    Separate from Blocker.supersedes_blocker_id so one blocker can be
    cited by multiple reviews (e.g. a re-review of the same unfixed
    failure) without mutating the blocker row.
    """

    __tablename__ = "review_blockers"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "blocker_id",
            name="uq_review_blockers_review_id_blocker_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Unique (review_id, blocker_id) above already indexes review_id
    # as the prefix column — no separate ix_review_blockers_review_id
    # needed. Keep an index on blocker_id for "reviews citing this
    # blocker" reverse lookups.
    review_id: UUID = Field(foreign_key="reviews.id")
    blocker_id: UUID = Field(foreign_key="blockers.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
