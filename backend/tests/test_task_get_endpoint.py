# ruff: noqa: INP001
"""Coverage for the single-task GET endpoint at ``/tasks/{task_id}``.

The endpoint replaces the prior client pattern of paginating the entire
list endpoint to find one task — exercised by ``mc_client.py task-read``
and the ``mc_task_read`` MCP tool.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.tasks import _task_read_page, get_task
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task


async def _seed_board_and_task(session: AsyncSession) -> tuple[Board, Task]:
    org = Organization(name="acme")
    session.add(org)
    await session.commit()
    await session.refresh(org)

    board = Board(name="dev-squad", slug="dev-squad", organization_id=org.id)
    session.add(board)
    await session.commit()
    await session.refresh(board)

    task = Task(
        board_id=board.id,
        title="Build the thing",
        description="With evidence.",
        status="inbox",
        review_packet_type="frontend_ui",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, task


@pytest.mark.asyncio
async def test_get_task_returns_task_envelope(sqlite_session: AsyncSession) -> None:
    """Happy path: handler returns the TaskRead envelope for the task."""
    _, task = await _seed_board_and_task(sqlite_session)

    result = await get_task(task=task, session=sqlite_session)

    assert result.id == task.id
    assert result.title == "Build the thing"
    assert result.status == "inbox"
    assert result.review_packet_type == "frontend_ui"


@pytest.mark.asyncio
async def test_get_task_404_when_task_has_no_board(
    sqlite_session: AsyncSession,
) -> None:
    """Defensive: a task without a board_id is treated as not-found."""
    orphan = Task(board_id=None, title="orphan")  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc:
        await get_task(task=orphan, session=sqlite_session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_task_projects_open_blocker_reason_codes(
    sqlite_session: AsyncSession,
) -> None:
    """User-side single-task GET must surface ``open_blocker_reason_codes``
    so the operator UI / dashboards can show what the task is blocked
    on. Production gap 2026-05-04 (QA gate task 5b7abdd2): ``is_blocked``
    flipped to true after Supervisor filed structured Blockers, but the
    inline projection returned ``open_blocker_reason_codes=null``,
    masking the BLOCKER FILED visibility surface that lead-health-scan
    mandates. Agent-side endpoint already enriches this; user-side
    ``_task_read_page`` did not."""
    board, task = await _seed_board_and_task(sqlite_session)
    sqlite_session.add(
        Blocker(
            board_id=board.id,
            task_id=task.id,
            category="source",
            reason_code="operator_reject_demo",
            owner_role="programmer_frontend",
        ),
    )
    await sqlite_session.commit()

    page = await _task_read_page(
        session=sqlite_session,
        board_id=board.id,
        tasks=[task],
    )
    assert page
    read = page[0]
    assert read.is_blocked is True
    assert read.open_blocker_reason_codes == ["operator_reject_demo"]


@pytest.mark.asyncio
async def test_get_task_projects_pending_operator_decision_reason_codes(
    sqlite_session: AsyncSession,
) -> None:
    """Same projection bug applies to ``pending_operator_decision_reason_codes``
    — the user-side serializer was missing both list enrichments."""
    from app.models.operator_decisions import OperatorDecision, OperatorDecisionTaskLink

    board, task = await _seed_board_and_task(sqlite_session)
    decision = OperatorDecision(
        board_id=board.id,
        question="Pick A or B",
        reason_code="operator_decision_demo",
    )
    sqlite_session.add(decision)
    await sqlite_session.commit()
    sqlite_session.add(
        OperatorDecisionTaskLink(
            board_id=board.id,
            decision_id=decision.id,
            task_id=task.id,
        ),
    )
    await sqlite_session.commit()

    page = await _task_read_page(
        session=sqlite_session,
        board_id=board.id,
        tasks=[task],
    )
    assert page
    read = page[0]
    assert read.pending_operator_decision_reason_codes == ["operator_decision_demo"]


@pytest.mark.asyncio
async def test_get_task_envelope_matches_list_endpoint_shape(
    sqlite_session: AsyncSession,
) -> None:
    """The single-task envelope must match the list-page item shape so
    callers can swap from list-then-filter to single-task-GET without
    reshaping their consumers."""
    from app.api.tasks import _task_read_page

    board, task = await _seed_board_and_task(sqlite_session)

    single = await get_task(task=task, session=sqlite_session)
    page = await _task_read_page(session=sqlite_session, board_id=board.id, tasks=[task])

    assert page, "list-page transformer should yield one row"
    assert single.model_dump() == page[0].model_dump()


@pytest.mark.asyncio
async def test_get_task_handler_does_not_query_other_tasks(
    sqlite_session: AsyncSession,
) -> None:
    """Sanity: with 50 unrelated tasks on the same board, fetching one
    by id stays cheap (the handler should not paginate the board).
    """
    from sqlalchemy import event as sa_event

    org = Organization(name="acme")
    sqlite_session.add(org)
    await sqlite_session.commit()
    await sqlite_session.refresh(org)

    board = Board(name="dev-squad", slug="dev-squad", organization_id=org.id)
    sqlite_session.add(board)
    await sqlite_session.commit()
    await sqlite_session.refresh(board)

    target_task = Task(board_id=board.id, title="target")
    other_tasks = [Task(board_id=board.id, title=f"noise-{i}") for i in range(50)]
    sqlite_session.add_all([target_task, *other_tasks])
    await sqlite_session.commit()
    await sqlite_session.refresh(target_task)

    bind = sqlite_session.bind
    assert bind is not None
    sync_engine = getattr(bind, "sync_engine", bind)

    query_count = 0

    @sa_event.listens_for(sync_engine, "before_cursor_execute")
    def _count(*_args: object, **_kwargs: object) -> None:
        nonlocal query_count
        query_count += 1

    try:
        result = await get_task(task=target_task, session=sqlite_session)
        assert result.id == target_task.id
        # Single-task GET should issue a small constant number of queries
        # (enrichments via _task_read_page); should not scan all 51 rows
        # via per-row lookups.
        assert query_count < 20, (
            f"Expected < 20 queries for one task; got {query_count}. "
            "Likely regressed to per-task fan-out."
        )
    finally:
        sa_event.remove(sync_engine, "before_cursor_execute", _count)
