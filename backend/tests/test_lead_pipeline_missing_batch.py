# ruff: noqa: INP001
"""Verify the lead-loop pipeline-missing N+1 fix.

``_lead_pipeline_missing_by_task_id`` (agent.py) used to fire one
``list_task_pipeline_events`` query per frontend pipeline task. This
test pins the constant-query contract — N tasks must produce 1 SQL
query, not N.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.agent import _lead_pipeline_missing_by_task_id
from app.core.time import utcnow
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.tasks import Task


def _frontend_task(board_id: UUID) -> Task:
    return Task(
        id=uuid4(),
        board_id=board_id,
        title=f"frontend-{uuid4()}",
        status="in_progress",
        review_packet_type="frontend_ui",
        in_progress_at=utcnow() - timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_lead_pipeline_missing_batch_uses_one_query_for_n_tasks() -> None:
    """5 frontend pipeline tasks must produce exactly 1 query."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)

    query_count = 0

    @sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(*_args: object, **_kwargs: object) -> None:
        nonlocal query_count
        query_count += 1

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            board_id = uuid4()
            tasks = [_frontend_task(board_id) for _ in range(5)]
            session.add_all(tasks)
            # Each task gets a couple of pipeline events
            for task in tasks:
                session.add(
                    TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task.id,
                        agent_id=None,
                        state="code_changed",
                        source="test",
                        created_at=utcnow(),
                    )
                )
                session.add(
                    TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task.id,
                        agent_id=None,
                        state="committed",
                        source="test",
                        commit_sha="abc1234",
                        created_at=utcnow(),
                    )
                )
            await session.commit()

            query_count = 0
            result = await _lead_pipeline_missing_by_task_id(session, tasks=tasks)

            assert len(result) == 5
            # All 5 tasks have only code_changed + committed; the rest of
            # the frontend pipeline frontier (built, deployed, …) is
            # missing.
            for missing in result.values():
                assert "built" in missing
                assert "code_changed" not in missing  # already present
            assert query_count == 1, (
                f"expected 1 batch query for 5 frontend tasks; got {query_count}"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_pipeline_missing_skips_non_frontend_tasks() -> None:
    """Backend / infra packet types are filtered before the SQL fetch.

    With NO frontend tasks in the batch, no query should fire at all.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)

    query_count = 0

    @sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(*_args: object, **_kwargs: object) -> None:
        nonlocal query_count
        query_count += 1

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            board_id = uuid4()
            tasks = [
                Task(
                    id=uuid4(),
                    board_id=board_id,
                    title="api-task",
                    status="in_progress",
                    review_packet_type="backend_api",
                    in_progress_at=utcnow(),
                ),
                Task(
                    id=uuid4(),
                    board_id=board_id,
                    title="infra-task",
                    status="review",
                    review_packet_type="infra_ops",
                    in_progress_at=utcnow(),
                ),
            ]
            session.add_all(tasks)
            await session.commit()

            query_count = 0
            result = await _lead_pipeline_missing_by_task_id(session, tasks=tasks)

            assert result == {}
            assert query_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_pipeline_missing_applies_per_task_cycle_since() -> None:
    """A fallback event from a previous cycle must not satisfy the
    current cycle's frontier.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            board_id = uuid4()
            current_cycle_start = utcnow()
            previous_cycle_event_at = current_cycle_start - timedelta(days=1)

            task = Task(
                id=uuid4(),
                board_id=board_id,
                title="restarted-task",
                status="in_progress",
                review_packet_type="frontend_ui",
                in_progress_at=current_cycle_start,
            )
            session.add(task)
            # An old "committed" event — from the previous cycle — must
            # not contribute to the current frontier
            session.add(
                TaskPipelineEvent(
                    id=uuid4(),
                    board_id=board_id,
                    task_id=task.id,
                    agent_id=None,
                    state="committed",
                    source="test",
                    commit_sha="old-sha",
                    created_at=previous_cycle_event_at,
                )
            )
            await session.commit()

            result = await _lead_pipeline_missing_by_task_id(session, tasks=[task])

            assert task.id in result
            # No present states → all frontend pipeline states still missing
            assert "code_changed" in result[task.id]
            assert "committed" in result[task.id]
    finally:
        await engine.dispose()
