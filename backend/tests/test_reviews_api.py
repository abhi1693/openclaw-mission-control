# ruff: noqa: INP001
"""Integration tests for Phase II Review endpoints (plan §I4).

Covers the FAIL-requires-blocker invariant at the schema layer and
the atomic Review + Blocker + ReviewBlocker write at the handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.reviews import (
    _blockers_by_review,
    _review_read,
    create_task_review,
)
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.reviews import Review, ReviewBlocker
from app.models.tasks import Task
from app.schemas.reviews import ReviewBlockerDescriptor, ReviewCreate


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[tuple[AsyncSession, Board, Task, _ActorStub]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)

    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()
    task_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.example.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Phase II review board",
        slug="phase-ii-reviews",
        description="Seeded for review API tests.",
    )
    session.add(board)
    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Reviewer Agent",
        status="online",
        openclaw_session_id="reviewer:session",
    )
    session.add(agent)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Test task",
        status="review",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    try:
        yield session, board, task, _ActorStub(agent=agent)
    finally:
        await session.close()
        await engine.dispose()


def _descriptor(**overrides: object) -> ReviewBlockerDescriptor:
    defaults: dict[str, object] = {
        "category": "source",
        "owner_role": "frontend-dev",
    }
    defaults.update(overrides)
    return ReviewBlockerDescriptor.model_validate(defaults)


def test_fail_without_blockers_rejected_at_schema_layer() -> None:
    """§I4: FAIL with zero blockers returns 422 — the schema-level
    validator is the 422 source so handler writes are unreachable."""

    with pytest.raises(ValidationError):
        ReviewCreate.model_validate({"verdict": "fail", "blockers": []})


def test_pass_without_blockers_accepted() -> None:
    """PASS / needs_changes do not require structured blockers."""

    review = ReviewCreate.model_validate({"verdict": "pass"})
    assert review.blockers == []


@pytest.mark.asyncio
async def test_fail_with_blockers_creates_review_and_linked_blockers(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    read = await create_task_review(
        payload=ReviewCreate(
            verdict="fail",
            citation="See attached trace",
            blockers=[
                _descriptor(category="deploy", owner_role="platform-dev"),
                _descriptor(category="contract", owner_role="backend-dev"),
            ],
        ),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert read.verdict == "fail"
    assert read.reviewer_agent_id == actor.agent.id  # type: ignore[union-attr]
    assert len(read.blockers) == 2
    assert {b.category for b in read.blockers} == {"deploy", "contract"}

    blocker_rows = (
        await session.exec(
            select(Blocker).where(col(Blocker.task_id) == task.id)
        )
    ).all()
    assert len(blocker_rows) == 2
    link_rows = (
        await session.exec(
            select(ReviewBlocker).where(col(ReviewBlocker.review_id) == read.id)
        )
    ).all()
    assert len(link_rows) == 2


@pytest.mark.asyncio
async def test_pass_verdict_creates_review_without_blockers(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    read = await create_task_review(
        payload=ReviewCreate(verdict="pass", citation="LGTM"),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert read.verdict == "pass"
    assert read.blockers == []
    assert (
        (
            await session.exec(
                select(Blocker).where(col(Blocker.task_id) == task.id)
            )
        ).all()
        == []
    )


@pytest.mark.asyncio
async def test_list_reviews_hydrates_blockers(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    await create_task_review(
        payload=ReviewCreate(
            verdict="fail",
            blockers=[_descriptor(category="runtime", owner_role="backend-dev")],
        ),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    reviews = (
        await session.exec(
            select(Review).where(col(Review.task_id) == task.id)
        )
    ).all()
    assert len(reviews) == 1
    blockers_by_id = await _blockers_by_review(session, [reviews[0].id])
    hydrated = _review_read(reviews[0], blockers_by_id[reviews[0].id])
    assert len(hydrated.blockers) == 1
    assert hydrated.blockers[0].category == "runtime"


@pytest.mark.asyncio
async def test_per_blocker_citation_persists(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Per-blocker ``citation`` from ReviewBlockerDescriptor must land
    on the Blocker row AND surface in the response — it was silently
    dropped before the fix."""

    session, board, task, actor = seeded
    read = await create_task_review(
        payload=ReviewCreate(
            verdict="fail",
            blockers=[
                _descriptor(
                    category="deploy",
                    owner_role="platform-dev",
                    citation="see deploy log line 42",
                ),
            ],
        ),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert read.blockers[0].citation == "see deploy log line 42"
    persisted = (
        await session.exec(
            select(Blocker).where(col(Blocker.id) == read.blockers[0].blocker_id)
        )
    ).first()
    assert persisted is not None
    assert persisted.citation == "see deploy log line 42"


@pytest.mark.xfail(
    strict=True,
    reason="Phase III: before_flush hook will reject FAIL reviews with zero linked blockers",
)
@pytest.mark.asyncio
async def test_orm_path_rejects_fail_without_blocker(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """FAIL reviews with no blockers must be rejected at flush time,
    not just at the Pydantic layer. Today this XFAILS — direct ORM
    writes commit cleanly. When the hook lands, this flips green and
    becomes the regression guard for the invariant."""

    from sqlalchemy.exc import IntegrityError

    session, board, task, _actor = seeded
    session.add(
        Review(
            board_id=board.id,
            task_id=task.id,
            verdict="fail",
        ),
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.xfail(
    strict=True,
    reason="Phase III: before_flush hook will reject cross-task review↔blocker links",
)
@pytest.mark.asyncio
async def test_orm_path_rejects_cross_task_review_blocker_link(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """``ReviewBlocker`` must enforce review.task_id == blocker.task_id
    at flush time. Today this XFAILS — direct ORM writes commit cleanly.
    ``create_task_review`` never triggers this path (it creates
    same-task blockers inline), but the gap is visible to anyone who
    reaches for ``session.add(ReviewBlocker(...))`` directly. When the
    hook lands, this flips green and becomes the regression guard."""

    from sqlalchemy.exc import IntegrityError

    session, board, task, _actor = seeded
    other_task_id = uuid4()
    session.add(
        Task(
            id=other_task_id,
            board_id=board.id,
            title="Other task",
            status="in_progress",
        ),
    )
    other_blocker = Blocker(
        board_id=board.id,
        task_id=other_task_id,
        category="source",
        owner_role="frontend-dev",
    )
    session.add(other_blocker)
    review = Review(
        board_id=board.id,
        task_id=task.id,
        verdict="needs_changes",
    )
    session.add(review)
    await session.flush()
    session.add(ReviewBlocker(review_id=review.id, blocker_id=other_blocker.id))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_multiple_descriptors_are_distinct_blocker_rows(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Two descriptors with identical content must still create two
    separate Blocker rows — uniqueness only applies at the (review_id,
    blocker_id) pair, not at blocker content."""

    session, board, task, actor = seeded
    read = await create_task_review(
        payload=ReviewCreate(
            verdict="fail",
            blockers=[
                _descriptor(category="source", owner_role="frontend-dev"),
                _descriptor(category="source", owner_role="frontend-dev"),
            ],
        ),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert len({b.blocker_id for b in read.blockers}) == 2
