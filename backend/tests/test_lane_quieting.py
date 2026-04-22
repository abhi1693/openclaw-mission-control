# ruff: noqa: INP001
"""Unit tests for Phase VI §I6 blocked-lane comment suppression."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.lane_quieting import should_suppress_comment_for_blocked_lane


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[
    tuple[AsyncSession, Board, Task, Blocker]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)

    org = Organization(id=uuid4(), name="org")
    session.add(org)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        name="board",
        slug="board",
        description="x",
        rollout_flags={"structured_blockers_v1": True},
    )
    session.add(board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="in_progress",
        assigned_agent_id=uuid4(),
    )
    session.add(task)
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="source",
        owner_role="frontend-dev",
        acknowledged_at=datetime.now(timezone.utc),
    )
    session.add(blocker)
    await session.commit()
    try:
        yield session, board, task, blocker
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_owner_agent_suppressed_when_board_graduated(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    session, _board, task, _blocker = seeded
    assert await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),  # not task.assigned_agent_id
    )


@pytest.mark.asyncio
async def test_owner_agent_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """The task owner is explicitly exempt — they must still be able
    to post progress while the rest of the lane is quiet."""

    session, _board, task, _blocker = seeded
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=task.assigned_agent_id,
    )


@pytest.mark.asyncio
async def test_user_operator_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """User-token callers (human operators) are represented by
    ``author_agent_id=None`` — always allowed."""

    session, _board, task, _blocker = seeded
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=None,
    )


@pytest.mark.asyncio
async def test_rollout_flag_off_keeps_legacy_behaviour(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Boards without ``structured_blockers_v1`` don't opt into lane
    quieting — every agent can still comment."""

    session, board, task, _blocker = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_unacknowledged_blocker_does_not_suppress(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Unacknowledged blockers still need traffic so the owner can
    pick them up — suppression only kicks in after ack."""

    session, _board, task, blocker = seeded
    blocker.acknowledged_at = None
    session.add(blocker)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_resolved_blocker_does_not_suppress(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Once a blocker is resolved the lane re-opens."""

    session, _board, task, blocker = seeded
    blocker.resolved_at = datetime.now(timezone.utc)
    session.add(blocker)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_task_without_blockers_is_open(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """A task with no blocker rows at all is open to every commenter."""

    session, board, _task, _blocker = seeded
    bare_task = Task(
        id=uuid4(),
        board_id=board.id,
        title="bare",
        status="in_progress",
    )
    session.add(bare_task)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=bare_task,
        author_agent_id=uuid4(),
    )
