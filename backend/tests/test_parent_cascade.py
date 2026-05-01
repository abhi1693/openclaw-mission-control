# ruff: noqa: INP001
"""Phase V parent-child cascade: orphan detection + cancel_orphan_child action."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.lead_next_action import select_lead_next_action
from app.services.parent_cascade import non_terminal_children_of


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_board(session: AsyncSession) -> tuple[object, object, object]:
    org_id = uuid4()
    board_id = uuid4()
    gateway_id = uuid4()
    session.add(Organization(id=org_id, name="org"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.local",
            workspace_root="/tmp/workspace",
        ),
    )
    session.add(
        Board(
            id=board_id,
            organization_id=org_id,
            name="board",
            slug="board",
            gateway_id=gateway_id,
        ),
    )
    await session.commit()
    return org_id, board_id, gateway_id


def _task(
    *,
    status: str = "inbox",
    title: str = "T",
    assigned: bool = False,
    parent_task_id=None,
) -> Task:
    return Task(
        id=uuid4(),
        board_id=uuid4(),
        title=title,
        status=status,
        assigned_agent_id=uuid4() if assigned else None,
        parent_task_id=parent_task_id,
    )


def test_orphan_child_action_returned_when_parent_terminal_and_child_active() -> None:
    parent = _task(status="done", title="Parent — shipped")
    child = _task(status="rework", title="Obsolete child", assigned=True)

    action = select_lead_next_action(
        tasks=[parent, child],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={child.id: parent.id},
    )

    assert action.action_required is True
    assert action.action == "cancel_orphan_child"
    assert action.reason_code == "non_terminal_child_of_terminal_parent"
    assert action.task_id == child.id
    assert action.details["parent_task_id"] == str(parent.id)
    assert action.details["orphan_count"] == 1


def test_orphan_action_overrides_route_inbox() -> None:
    """If both an unassigned inbox task AND an orphan child exist, drain the
    orphan first — cleanup of obsolete decomposition wins over allocating
    fresh inbox attention."""
    parent = _task(status="cancelled", title="Cancelled parent")
    orphan = _task(status="rework", title="Orphan rework", assigned=True)
    fresh_inbox = _task(status="inbox", title="Fresh routable inbox")

    action = select_lead_next_action(
        tasks=[parent, orphan, fresh_inbox],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == orphan.id


def test_review_action_still_wins_over_orphan() -> None:
    """An active review task ranks above orphan cleanup — real work first."""
    parent = _task(status="done")
    orphan = _task(status="rework", assigned=True)
    review_task = _task(status="review", title="Real review work")

    action = select_lead_next_action(
        tasks=[parent, orphan, review_task],
        blocked_by_task_id={},
        approval_state_by_task_id={review_task.id: "none"},
        pipeline_missing_by_task_id={},
        review_readiness_by_task_id={review_task.id: {"ready": True}},
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "inspect_review_gates"
    assert action.task_id == review_task.id


def test_orphan_action_skipped_when_orphan_map_empty() -> None:
    inbox_task = _task(status="inbox")

    action = select_lead_next_action(
        tasks=[inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={},
    )

    assert action.action == "route_inbox"


def test_orphan_action_skipped_when_kwarg_omitted() -> None:
    """Backwards-compat: callers that don't pass the orphan map see no
    change in behavior — the kwarg defaults to None."""
    inbox_task = _task(status="inbox")

    action = select_lead_next_action(
        tasks=[inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action == "route_inbox"


def test_orphan_action_uses_lowest_id_for_determinism() -> None:
    parent = _task(status="done")
    # Two orphans with different ids; action should pick the one with the
    # lexicographically smaller string id.
    orphan_a = _task(status="rework", title="A")
    orphan_b = _task(status="inbox", title="B")
    smaller = sorted([orphan_a, orphan_b], key=lambda t: str(t.id))[0]

    action = select_lead_next_action(
        tasks=[parent, orphan_a, orphan_b],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={
            orphan_a.id: parent.id,
            orphan_b.id: parent.id,
        },
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == smaller.id
    assert action.details["orphan_count"] == 2


def test_orphan_with_blocker_still_surfaces() -> None:
    """An orphan child can carry its own waiting flags (open Blocker, pending
    OperatorDecision, etc.) — those don't disqualify it from cleanup. The
    parent terminating already declared the work moot."""
    parent = _task(status="done")
    orphan = _task(status="rework", assigned=True)

    action = select_lead_next_action(
        tasks=[parent, orphan],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_open_blocker=frozenset({orphan.id}),
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == orphan.id


def test_orphan_action_skipped_when_child_already_terminal() -> None:
    """If the orphan map happens to contain a child that's now terminal
    (race between snapshot read and selection), skip it."""
    parent = _task(status="done")
    already_done_child = _task(status="cancelled")

    action = select_lead_next_action(
        tasks=[parent, already_done_child],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={already_done_child.id: parent.id},
    )

    assert action.action == "clear"


# Integration tests for the validator + cascade query — exercise real
# DB paths called out in the 2026-05-01 codex review.


@pytest.mark.asyncio
async def test_validate_parent_task_id_rejects_self_parent() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _, board_id, _ = await _seed_board(session)
            task_id = uuid4()
            with pytest.raises(HTTPException) as excinfo:
                await tasks_api._validate_parent_task_id(
                    session,
                    board_id=board_id,
                    task_id=task_id,
                    parent_task_id=task_id,
                )
            assert excinfo.value.status_code == 422
            assert "own parent" in excinfo.value.detail["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_validate_parent_task_id_rejects_unknown_parent() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _, board_id, _ = await _seed_board(session)
            with pytest.raises(HTTPException) as excinfo:
                await tasks_api._validate_parent_task_id(
                    session,
                    board_id=board_id,
                    task_id=uuid4(),
                    parent_task_id=uuid4(),
                )
            assert excinfo.value.status_code == 422
            assert "not found" in excinfo.value.detail["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_validate_parent_task_id_rejects_cross_board_parent() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _, board_id_a, _ = await _seed_board(session)
            _, board_id_b, _ = await _seed_board(session)
            parent = Task(
                id=uuid4(),
                board_id=board_id_a,
                title="parent-on-board-a",
                status="inbox",
            )
            session.add(parent)
            await session.commit()

            with pytest.raises(HTTPException) as excinfo:
                await tasks_api._validate_parent_task_id(
                    session,
                    board_id=board_id_b,
                    task_id=uuid4(),
                    parent_task_id=parent.id,
                )
            assert excinfo.value.status_code == 422
            assert "different board" in excinfo.value.detail["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_validate_parent_task_id_rejects_terminal_parent() -> None:
    """Codex 2026-05-01: a child born under an already-terminal parent
    is born orphaned and never gets a transition event. Reject at
    create-time instead."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _, board_id, _ = await _seed_board(session)
            parent = Task(
                id=uuid4(),
                board_id=board_id,
                title="terminal-parent",
                status="done",
            )
            session.add(parent)
            await session.commit()

            with pytest.raises(HTTPException) as excinfo:
                await tasks_api._validate_parent_task_id(
                    session,
                    board_id=board_id,
                    task_id=uuid4(),
                    parent_task_id=parent.id,
                )
            assert excinfo.value.status_code == 422
            assert "born orphaned" in excinfo.value.detail["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_terminal_children_of_returns_only_active_children() -> None:
    """Verify the cascade query filter: terminal children are excluded,
    children on other boards are excluded, and ordering is stable
    by created_at."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _, board_id, _ = await _seed_board(session)
            parent_id = uuid4()
            session.add(
                Task(id=parent_id, board_id=board_id, title="parent", status="done"),
            )
            child_a = Task(
                id=uuid4(),
                board_id=board_id,
                title="child-a-active",
                status="rework",
                parent_task_id=parent_id,
            )
            child_b_terminal = Task(
                id=uuid4(),
                board_id=board_id,
                title="child-b-cancelled",
                status="cancelled",
                parent_task_id=parent_id,
            )
            child_c = Task(
                id=uuid4(),
                board_id=board_id,
                title="child-c-active",
                status="inbox",
                parent_task_id=parent_id,
            )
            session.add_all([child_a, child_b_terminal, child_c])
            await session.commit()

            children = await non_terminal_children_of(
                session, board_id=board_id, parent_task_id=parent_id
            )

            assert child_a.id in children
            assert child_c.id in children
            assert child_b_terminal.id not in children
            assert len(children) == 2
    finally:
        await engine.dispose()
