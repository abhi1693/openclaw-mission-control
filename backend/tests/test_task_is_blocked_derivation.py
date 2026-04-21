# ruff: noqa: INP001
"""Unit test for the Phase II is_blocked derivation (plan §I1).

``_task_is_blocked`` gained a third OR: an open ``Blocker`` row counts
as blocked even when the dependency graph is clean. The helper + its
batch preloader are decoupled from the handler, so this covers the
derivation contract without spinning up the whole task stack.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.tasks import _task_is_blocked
from app.models.blockers import Blocker
from app.models.tasks import Task
from app.services.blockers import task_has_open_blocker, task_ids_with_open_blocker


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


def _task(**overrides: object) -> Task:
    defaults: dict[str, object] = {
        "board_id": uuid4(),
        "title": "Example",
        "status": "in_progress",
    }
    defaults.update(overrides)
    return Task(**defaults)  # type: ignore[arg-type]


def test_open_blocker_flag_flips_is_blocked_true() -> None:
    """An open blocker counts even when the dependency graph is empty."""

    task = _task()
    assert not _task_is_blocked(task, [])
    assert _task_is_blocked(task, [], has_open_blocker=True)


def test_terminal_status_still_clears_open_blocker() -> None:
    """Done/cancelled tasks are not blocked regardless of blockers."""

    for status in ("done", "cancelled"):
        task = _task(status=status)
        assert not _task_is_blocked(task, [], has_open_blocker=True)


@pytest.mark.asyncio
async def test_scalar_exists_returns_false_on_empty_table(
    db_session: AsyncSession,
) -> None:
    """task_has_open_blocker on a task with no rows must be False —
    guards against a ``Row``-truthiness false positive."""

    assert not await task_has_open_blocker(
        db_session, board_id=uuid4(), task_id=uuid4()
    )


@pytest.mark.asyncio
async def test_scalar_exists_honors_resolved_at(
    db_session: AsyncSession,
) -> None:
    """Resolved blockers must not satisfy the EXISTS clause."""

    board_id = uuid4()
    open_task_id = uuid4()
    resolved_task_id = uuid4()
    db_session.add(
        Blocker(
            board_id=board_id,
            task_id=open_task_id,
            category="source",
            owner_role="dev",
        ),
    )
    resolved = Blocker(
        board_id=board_id,
        task_id=resolved_task_id,
        category="source",
        owner_role="dev",
    )
    db_session.add(resolved)
    await db_session.commit()
    resolved.resolved_at = resolved.created_at
    db_session.add(resolved)
    await db_session.commit()

    assert await task_has_open_blocker(
        db_session, board_id=board_id, task_id=open_task_id
    )
    assert not await task_has_open_blocker(
        db_session, board_id=board_id, task_id=resolved_task_id
    )


@pytest.mark.asyncio
async def test_batch_preloader_returns_only_open_blocker_task_ids(
    db_session: AsyncSession,
) -> None:
    """``task_ids_with_open_blocker`` must exclude resolved rows."""

    board_id = uuid4()
    open_task_id = uuid4()
    resolved_task_id = uuid4()
    no_blocker_task_id = uuid4()
    db_session.add(
        Blocker(
            board_id=board_id,
            task_id=open_task_id,
            category="source",
            owner_role="frontend-dev",
        ),
    )
    resolved = Blocker(
        board_id=board_id,
        task_id=resolved_task_id,
        category="source",
        owner_role="frontend-dev",
    )
    db_session.add(resolved)
    await db_session.commit()
    resolved.resolved_at = resolved.created_at
    db_session.add(resolved)
    await db_session.commit()

    blocked = await task_ids_with_open_blocker(
        db_session,
        board_id=board_id,
        task_ids=[open_task_id, resolved_task_id, no_blocker_task_id],
    )
    assert blocked == {open_task_id}
