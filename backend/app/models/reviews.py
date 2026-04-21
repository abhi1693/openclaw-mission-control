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

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)

REVIEW_VERDICTS = ("pass", "fail", "needs_changes")


class Review(TenantScoped, table=True):
    """Structured review verdict on a task."""

    __tablename__ = "reviews"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'fail', 'needs_changes')",
            name="ck_reviews_verdict_values",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    verdict: str
    summary: str | None = None
    # Citation keeps the reviewer's narrative — the routing data lives
    # in the linked blocker rows. Kept text, not JSON, so the Supervisor
    # can render it inline without schema churn.
    citation: str | None = None
    reviewer_agent_id: UUID | None = Field(
        default=None, foreign_key="agents.id", index=True
    )
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
    review_id: UUID = Field(foreign_key="reviews.id", index=True)
    blocker_id: UUID = Field(foreign_key="blockers.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
