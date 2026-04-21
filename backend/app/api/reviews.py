"""Phase II Review endpoints (plan §I4).

A ``POST /reviews`` submission creates the ``Review`` row plus one
``Blocker`` + ``ReviewBlocker`` row per descriptor in a single
transaction. ``FAIL`` with zero blockers is already rejected at the
schema layer (422); the handler owns the atomic write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, status
from sqlmodel import col, select

from app.api.deps import (
    ACTOR_DEP,
    SESSION_DEP,
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    get_task_or_404,
)
from app.db.pagination import paginate
from app.models.blockers import Blocker
from app.models.reviews import Review, ReviewBlocker
from app.models.tasks import Task
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.reviews import ReviewBlockerRead, ReviewCreate, ReviewRead

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(
    prefix="/boards/{board_id}/tasks/{task_id}/reviews", tags=["reviews"]
)

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
TASK_DEP = Depends(get_task_or_404)


async def _hydrate_review(
    session: "AsyncSession", review: Review
) -> ReviewRead:
    """Load the review's linked blockers and build a ReviewRead."""

    stmt = (
        select(ReviewBlocker, Blocker)
        .join(Blocker, col(ReviewBlocker.blocker_id) == col(Blocker.id))
        .where(col(ReviewBlocker.review_id) == review.id)
        .order_by(col(ReviewBlocker.created_at).asc())
    )
    rows = (await session.exec(stmt)).all()
    return ReviewRead(
        id=review.id,
        board_id=review.board_id,
        task_id=review.task_id,
        verdict=review.verdict,  # type: ignore[arg-type]
        citation=review.citation,
        reviewer_agent_id=review.reviewer_agent_id,
        created_at=review.created_at,
        blockers=[
            ReviewBlockerRead(
                id=link.id,
                blocker_id=blocker.id,
                category=blocker.category,  # type: ignore[arg-type]
                owner_role=blocker.owner_role,
                required_artifact=blocker.required_artifact,
                target_env=blocker.target_env,
                reopen_condition=blocker.reopen_condition,
            )
            for link, blocker in rows
        ],
    )


@router.get("", response_model=DefaultLimitOffsetPage[ReviewRead])
async def list_task_reviews(
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> "LimitOffsetPage[ReviewRead]":
    """List reviews on the task, newest first. Blockers are hydrated
    per row — at pagination-default limits this is bounded."""

    async def _transform(rows: "Sequence[object]") -> list[ReviewRead]:
        reviews: list[Review] = []
        for row in rows:
            if not isinstance(row, Review):
                msg = "Expected Review rows from reviews pagination query."
                raise TypeError(msg)
            reviews.append(row)
        return [await _hydrate_review(session, review) for review in reviews]

    statement = (
        Review.objects.filter_by(task_id=task.id)
        .order_by(Review.created_at.desc())
        .statement
    )
    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_task_review(
    payload: ReviewCreate,
    board: "Board" = BOARD_WRITE_DEP,
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> ReviewRead:
    """Submit a review verdict. FAIL verdicts require inline blockers;
    that guard lives on ``ReviewCreate`` and surfaces as 422."""

    review = Review(
        board_id=board.id,
        task_id=task.id,
        verdict=payload.verdict,
        citation=payload.citation,
        reviewer_agent_id=actor.agent.id if actor.agent is not None else None,
    )
    session.add(review)
    # Flush so review.id is allocated without committing — the linked
    # blocker + join rows go in the same transaction.
    await session.flush()

    for descriptor in payload.blockers:
        blocker = Blocker(
            board_id=board.id,
            task_id=task.id,
            category=descriptor.category,
            owner_role=descriptor.owner_role,
            required_artifact=descriptor.required_artifact,
            target_env=descriptor.target_env,
            reopen_condition=descriptor.reopen_condition,
            created_by_agent_id=review.reviewer_agent_id,
        )
        session.add(blocker)
        await session.flush()
        session.add(ReviewBlocker(review_id=review.id, blocker_id=blocker.id))

    await session.commit()
    await session.refresh(review)
    return await _hydrate_review(session, review)
