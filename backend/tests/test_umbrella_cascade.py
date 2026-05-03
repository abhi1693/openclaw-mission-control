# ruff: noqa: INP001
"""Umbrella auto-cascade — when the last child of a never-executed
umbrella reaches terminal status, the umbrella itself must auto-cancel.

Repro 2026-05-03: ``a8a67bc8`` (Phase 2.5 Stats + trust-line truth packet)
was decomposed into 5 child tasks (AC1-AC5). All children eventually
reached ``done``, but the umbrella sat in ``inbox`` indefinitely with
``is_blocked=False`` (deps satisfied) and no assignee — pure queue
pollution that surfaced as "why is this stuck?" in the operator's
dashboard view.

Invariant pinned by these tests:
- Last sibling reaching done/cancelled triggers parent auto-cancel
- Cascade ONLY fires when parent has never been executed (no
  ``in_progress_at`` AND no ``previous_in_progress_at``)
- Cascade does not touch parents that are already terminal
- Cascade does not touch parents whose siblings are still active
- Tasks with no parent are no-ops
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.parent_cascade import maybe_cascade_umbrella_close


async def _seed_board(session: AsyncSession, *, slug: str) -> Board:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{slug}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{slug}",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name=slug,
        slug=slug,
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


async def _seed_umbrella_with_children(
    session: AsyncSession,
    *,
    board: Board,
    n_children: int,
    child_status: str = "done",
    parent_in_progress_at: datetime | None = None,
    parent_previous_in_progress_at: datetime | None = None,
) -> tuple[Task, list[Task]]:
    """Seed an umbrella parent and N children at the requested status."""
    parent = Task(
        id=uuid4(),
        board_id=board.id,
        title=f"umbrella-{board.slug}",
        status="inbox",
        in_progress_at=parent_in_progress_at,
        previous_in_progress_at=parent_previous_in_progress_at,
    )
    session.add(parent)
    children: list[Task] = []
    for i in range(n_children):
        child = Task(
            id=uuid4(),
            board_id=board.id,
            title=f"child-{i}",
            status=child_status,
            parent_task_id=parent.id,
        )
        session.add(child)
        children.append(child)
    await session.commit()
    await session.refresh(parent)
    for c in children:
        await session.refresh(c)
    return parent, children


@pytest.mark.asyncio
async def test_cascade_fires_when_last_child_reaches_done(
    sqlite_session: AsyncSession,
) -> None:
    """AC: every sibling done -> parent auto-cancels."""
    board = await _seed_board(sqlite_session, slug="cascade-happy")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=3, child_status="done",
    )
    assert parent.status == "inbox"

    # Trigger: pass the last "done" child to the cascade helper.
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])

    assert cascaded is not None, "cascade must fire when all siblings are terminal"
    assert cascaded.id == parent.id
    assert cascaded.status == "cancelled"
    assert cascaded.cancelled_at is not None


@pytest.mark.asyncio
async def test_cascade_fires_when_last_child_reaches_cancelled(
    sqlite_session: AsyncSession,
) -> None:
    """Cancelled siblings count as terminal too — they satisfy the
    cascade trigger same as done."""
    board = await _seed_board(sqlite_session, slug="cascade-cancelled-trigger")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=2, child_status="cancelled",
    )
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is not None
    assert cascaded.status == "cancelled"


@pytest.mark.asyncio
async def test_cascade_no_op_when_some_siblings_still_active(
    sqlite_session: AsyncSession,
) -> None:
    """If even one sibling is non-terminal, the parent must NOT close."""
    board = await _seed_board(sqlite_session, slug="cascade-active-sibling")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=3, child_status="done",
    )
    # Mutate one sibling back to in_progress.
    children[0].status = "in_progress"
    sqlite_session.add(children[0])
    await sqlite_session.commit()

    # The triggering done sibling shouldn't cascade because a peer is active.
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is None

    # And the parent must still be in inbox.
    await sqlite_session.refresh(parent)
    assert parent.status == "inbox"


@pytest.mark.asyncio
async def test_cascade_skips_parent_that_was_executed(
    sqlite_session: AsyncSession,
) -> None:
    """Safety net: if the parent has any execution history (in_progress
    or previous_in_progress), it's NOT a coordination umbrella and the
    cascade must not silently delete operator-attributed work."""
    board = await _seed_board(sqlite_session, slug="cascade-executed-parent")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session,
        board=board,
        n_children=2,
        child_status="done",
        parent_previous_in_progress_at=datetime(2026, 5, 1, 12, 0),
    )
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is None
    await sqlite_session.refresh(parent)
    assert parent.status == "inbox"


@pytest.mark.asyncio
async def test_cascade_skips_when_parent_already_terminal(
    sqlite_session: AsyncSession,
) -> None:
    """If parent already moved to done/cancelled by some other path,
    cascading again would be a no-op overwrite — skip cleanly."""
    board = await _seed_board(sqlite_session, slug="cascade-terminal-parent")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=1, child_status="done",
    )
    parent.status = "done"
    sqlite_session.add(parent)
    await sqlite_session.commit()
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is None


@pytest.mark.asyncio
async def test_cascade_no_op_when_task_has_no_parent(
    sqlite_session: AsyncSession,
) -> None:
    """Top-level tasks with no parent_task_id obviously can't cascade."""
    board = await _seed_board(sqlite_session, slug="cascade-no-parent")
    standalone = Task(
        id=uuid4(),
        board_id=board.id,
        title="standalone",
        status="done",
        parent_task_id=None,
    )
    sqlite_session.add(standalone)
    await sqlite_session.commit()
    await sqlite_session.refresh(standalone)
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=standalone)
    assert cascaded is None


@pytest.mark.asyncio
async def test_cascade_no_op_for_non_terminal_trigger(
    sqlite_session: AsyncSession,
) -> None:
    """The helper must not fire when the triggering task is in a
    non-terminal status (e.g. still in_progress). Only terminal
    transitions warrant a cascade attempt."""
    board = await _seed_board(sqlite_session, slug="cascade-non-terminal-trigger")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=2, child_status="done",
    )
    # Mutate the triggering task to in_progress; even though peers are
    # done, we shouldn't cascade off a non-terminal trigger.
    children[-1].status = "in_progress"
    sqlite_session.add(children[-1])
    await sqlite_session.commit()
    await sqlite_session.refresh(children[-1])
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is None


@pytest.mark.asyncio
async def test_cascade_records_activity_event(
    sqlite_session: AsyncSession,
) -> None:
    """Auto-cancel must leave an audit trail. Without it, dashboards
    show a parent that mysteriously moved from inbox to cancelled
    with no operator/agent attribution."""
    from sqlmodel import col, select

    from app.models.activity_events import ActivityEvent

    board = await _seed_board(sqlite_session, slug="cascade-activity-event")
    parent, children = await _seed_umbrella_with_children(
        sqlite_session, board=board, n_children=1, child_status="done",
    )
    cascaded = await maybe_cascade_umbrella_close(sqlite_session, task=children[-1])
    assert cascaded is not None
    await sqlite_session.commit()

    events = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == parent.id)
            .where(col(ActivityEvent.event_type) == "task.umbrella_auto_cascaded"),
        ),
    )
    assert len(events) == 1, (
        f"expected exactly one task.umbrella_auto_cascaded event for "
        f"the cancelled parent, got {len(events)}"
    )
    msg = events[0].message or ""
    assert str(children[-1].id) in msg, "message must reference the triggering child"


@pytest.mark.asyncio
async def test_cascade_recurses_through_multi_level_chain(
    sqlite_session: AsyncSession,
) -> None:
    """Grandparent umbrella retires too when its only non-terminal
    child (the parent) was just auto-cancelled. Without recursion,
    multi-level decomposition chains leak — the immediate parent
    closes but the grandparent stays in inbox forever."""
    board = await _seed_board(sqlite_session, slug="cascade-multi-level")

    # Build: grandparent -> parent -> child (all never-executed)
    grandparent = Task(
        id=uuid4(), board_id=board.id, title="grandparent",
        status="inbox", in_progress_at=None, previous_in_progress_at=None,
    )
    parent = Task(
        id=uuid4(), board_id=board.id, title="parent",
        status="inbox", in_progress_at=None, previous_in_progress_at=None,
        parent_task_id=grandparent.id,
    )
    child = Task(
        id=uuid4(), board_id=board.id, title="child",
        status="done", parent_task_id=parent.id,
    )
    sqlite_session.add(grandparent)
    sqlite_session.add(parent)
    sqlite_session.add(child)
    await sqlite_session.commit()
    await sqlite_session.refresh(grandparent)
    await sqlite_session.refresh(parent)
    await sqlite_session.refresh(child)

    cascaded_top = await maybe_cascade_umbrella_close(sqlite_session, task=child)

    # Grandparent is the topmost cascade target.
    assert cascaded_top is not None
    assert cascaded_top.id == grandparent.id
    # Both parent AND grandparent must have flipped to cancelled.
    await sqlite_session.refresh(parent)
    await sqlite_session.refresh(grandparent)
    assert parent.status == "cancelled"
    assert grandparent.status == "cancelled"
