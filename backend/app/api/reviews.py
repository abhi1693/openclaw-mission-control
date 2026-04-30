"""Phase II Review endpoints (plan §I4).

A ``POST /reviews`` submission creates the ``Review`` row plus one
``Blocker`` + ``ReviewBlocker`` row per descriptor in a single
transaction. ``FAIL`` with zero blockers is already rejected at the
schema layer (422); the handler owns the atomic write.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
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
    from collections.abc import Iterable, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(
    prefix="/boards/{board_id}/tasks/{task_id}/reviews", tags=["reviews"]
)

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
TASK_DEP = Depends(get_task_or_404)


def _to_review_blocker_read(
    link: ReviewBlocker, blocker: Blocker
) -> ReviewBlockerRead:
    return ReviewBlockerRead(
        id=link.id,
        blocker_id=blocker.id,
        category=blocker.category,  # type: ignore[arg-type]
        reason_code=blocker.reason_code,
        owner_role=blocker.owner_role,
        required_artifact=blocker.required_artifact,
        target_env=blocker.target_env,
        reopen_condition=blocker.reopen_condition,
        citation=blocker.citation,
    )


async def _blockers_by_review(
    session: "AsyncSession", review_ids: "Iterable[UUID]"
) -> dict[UUID, list[ReviewBlockerRead]]:
    """One SELECT + JOIN for all reviews on a page — avoids per-row N+1."""

    ids = list(review_ids)
    if not ids:
        return {}
    stmt = (
        select(ReviewBlocker, Blocker)
        .join(Blocker, col(ReviewBlocker.blocker_id) == col(Blocker.id))
        .where(col(ReviewBlocker.review_id).in_(ids))
        .order_by(col(ReviewBlocker.review_id), col(ReviewBlocker.created_at).asc())
    )
    grouped: dict[UUID, list[ReviewBlockerRead]] = defaultdict(list)
    for link, blocker in (await session.exec(stmt)).all():
        grouped[link.review_id].append(_to_review_blocker_read(link, blocker))
    return grouped


def _review_read(
    review: Review, blockers: list[ReviewBlockerRead]
) -> ReviewRead:
    return ReviewRead(
        id=review.id,
        board_id=review.board_id,
        task_id=review.task_id,
        verdict=review.verdict,  # type: ignore[arg-type]
        citation=review.citation,
        reviewer_agent_id=review.reviewer_agent_id,
        created_at=review.created_at,
        blockers=blockers,
    )


@router.get("", response_model=DefaultLimitOffsetPage[ReviewRead])
async def list_task_reviews(
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> "LimitOffsetPage[ReviewRead]":
    """List reviews on the task, newest first."""

    async def _transform(rows: "Sequence[object]") -> list[ReviewRead]:
        reviews: list[Review] = []
        for row in rows:
            if not isinstance(row, Review):
                msg = "Expected Review rows from reviews pagination query."
                raise TypeError(msg)
            reviews.append(row)
        blockers_by_id = await _blockers_by_review(
            session, (r.id for r in reviews)
        )
        return [
            _review_read(review, blockers_by_id.get(review.id, []))
            for review in reviews
        ]

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

    # Blocker.id and ReviewBlocker.id are Python-side uuid4 defaults,
    # so we can add the whole graph without intermediate flushes and
    # commit once. Synthesise the response from in-memory objects —
    # re-reading what we just wrote would be a wasted round trip.
    blocker_reads: list[ReviewBlockerRead] = []
    for descriptor in payload.blockers:
        blocker = Blocker(
            board_id=board.id,
            task_id=task.id,
            category=descriptor.category,
            reason_code=descriptor.reason_code,
            owner_role=descriptor.owner_role,
            required_artifact=descriptor.required_artifact,
            target_env=descriptor.target_env,
            reopen_condition=descriptor.reopen_condition,
            citation=descriptor.citation,
            created_by_agent_id=review.reviewer_agent_id,
        )
        session.add(blocker)
        link = ReviewBlocker(review_id=review.id, blocker_id=blocker.id)
        session.add(link)
        blocker_reads.append(_to_review_blocker_read(link, blocker))

    try:
        await session.commit()
    except IntegrityError as exc:
        # Part D added partial unique indexes on ``blockers``
        # (uq_blockers_runtime_owner_open,
        # uq_blockers_operator_artifact_open) so the feeder filers can
        # close their dedupe race. A reviewer FAIL that happens to file
        # the same (task, role/artifact) as an already-open auto-filed
        # blocker would trip the same constraint and 500 the whole
        # review. Surface as 409 so the reviewer gets an actionable
        # error instead of a server fault.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "A blocker in this review duplicates an already-open "
                    "auto-filed blocker for the same (task, owner/artifact). "
                    "Resolve or reference the existing row instead of "
                    "filing a new one."
                ),
                "code": "review_blocker_dedupe_conflict",
            },
        ) from exc
    return _review_read(review, blocker_reads)
