# ruff: noqa: INP001
"""Belt-and-suspenders board-wide sweep for pure-container umbrella retirement.

The dep-clear hook in ``_reconcile_dependents_for_dependency_toggle``
catches umbrellas that become eligible for retirement at the *moment*
their last dep transitions to done. It does NOT catch:
- Umbrellas whose deps cleared BEFORE this fix shipped (transition
  already passed; trigger gone).
- Umbrellas whose UMBRELLA_RETIRED marker was posted AFTER the deps had
  already cleared.
- Any umbrella that was missed by a transient failure on the dep-clear
  hook.

For all three, the lead heartbeat needs a sweep that finds qualifying
pure-container umbrellas and retires them. Symmetric in semantics to the
dep-clear hook — same preconditions, just discovered on the heartbeat
instead of on the transition.

These tests are RED until ``auto_retire_pure_container_umbrellas`` is
wired into the lead next-action endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.services.parent_cascade import auto_retire_pure_container_umbrellas


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Agent, Agent]]:
    """Seed org/gateway/board + lead + worker. Tests build their own
    umbrella + dep shapes on top."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{org_id}"))
    sqlite_session.add(
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
        name="sweep board",
        slug="sweep-board",
    )
    sqlite_session.add(board)
    lead = Agent(
        id=lead_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Supervisor",
        is_board_lead=True,
        openclaw_session_id="agent:lead:main",
    )
    worker = Agent(
        id=worker_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Programmer-Frontend",
        openclaw_session_id="agent:worker:main",
    )
    sqlite_session.add(lead)
    sqlite_session.add(worker)
    await sqlite_session.commit()
    yield sqlite_session, board, lead, worker


def _make_dep(*, board_id, worker_id, status="done") -> Task:
    return Task(
        id=uuid4(),
        board_id=board_id,
        title=f"Executable dep ({status})",
        status=status,
        assigned_agent_id=worker_id,
        in_progress_at=datetime(2026, 5, 5, 0, 0) if status != "inbox" else None,
    )


def _make_umbrella(*, board_id, lead_id) -> Task:
    return Task(
        id=uuid4(),
        board_id=board_id,
        title="Pure-container umbrella",
        status="inbox",
        assigned_agent_id=lead_id,
    )


def _seed_marker(session: AsyncSession, *, board_id, task_id, agent_id) -> None:
    session.add(
        ActivityEvent(
            board_id=board_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type="task.comment",
            message="UMBRELLA_RETIRED — pure-container closure disposition accepted.",
        ),
    )


@pytest.mark.asyncio
async def test_sweep_retires_umbrella_whose_dep_cleared_before_fix_shipped(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """The on-prod scenario: dep transitioned to done BEFORE the dep-clear
    hook existed. Marker is present, deps are all done, never-executed.
    The heartbeat sweep must find and retire this umbrella."""
    session, board, lead, worker = seeded
    dep = _make_dep(board_id=board.id, worker_id=worker.id, status="done")
    umbrella = _make_umbrella(board_id=board.id, lead_id=lead.id)
    session.add(dep)
    session.add(umbrella)
    session.add(
        TaskDependency(
            board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep.id
        ),
    )
    _seed_marker(session, board_id=board.id, task_id=umbrella.id, agent_id=lead.id)
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)
    await session.commit()

    await session.refresh(umbrella)
    assert umbrella.status == "cancelled"
    assert umbrella.id in {t.id for t in retired}


@pytest.mark.asyncio
async def test_sweep_retires_multiple_qualifying_umbrellas_in_one_pass(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """If two pure-container umbrellas qualify, both retire in one
    sweep call — the heartbeat shouldn't need multiple ticks to drain."""
    session, board, lead, worker = seeded
    umbrellas: list[Task] = []
    for _ in range(2):
        dep = _make_dep(board_id=board.id, worker_id=worker.id, status="done")
        umbrella = _make_umbrella(board_id=board.id, lead_id=lead.id)
        session.add(dep)
        session.add(umbrella)
        session.add(
            TaskDependency(
                board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep.id
            ),
        )
        _seed_marker(session, board_id=board.id, task_id=umbrella.id, agent_id=lead.id)
        umbrellas.append(umbrella)
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)

    retired_ids = {t.id for t in retired}
    for umbrella in umbrellas:
        await session.refresh(umbrella)
        assert umbrella.status == "cancelled"
        assert umbrella.id in retired_ids


@pytest.mark.asyncio
async def test_sweep_skips_umbrella_without_marker(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """Safety: a never-executed inbox task whose deps are all terminal
    must NOT retire if it lacks the UMBRELLA_RETIRED marker. Without
    the marker, this shape is indistinguishable from an ordinary task
    waiting on its prerequisite — auto-cancelling would surprise users."""
    session, board, lead, worker = seeded
    dep = _make_dep(board_id=board.id, worker_id=worker.id, status="done")
    umbrella = _make_umbrella(board_id=board.id, lead_id=lead.id)
    session.add(dep)
    session.add(umbrella)
    session.add(
        TaskDependency(
            board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep.id
        ),
    )
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)

    assert retired == []
    await session.refresh(umbrella)
    assert umbrella.status == "inbox"


@pytest.mark.asyncio
async def test_sweep_no_op_when_no_deps_or_children(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """Safety carve-out: a brand-new inbox task with neither deps nor
    parent_task_id children isn't a container — it's just work the
    operator hasn't decomposed yet. Sweep must NOT cancel it."""
    session, board, lead, _worker = seeded
    bare_task = Task(
        id=uuid4(),
        board_id=board.id,
        title="Bare inbox task — not yet decomposed",
        status="inbox",
        assigned_agent_id=lead.id,
    )
    session.add(bare_task)
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)

    assert retired == []
    await session.refresh(bare_task)
    assert bare_task.status == "inbox"


@pytest.mark.asyncio
async def test_sweep_skips_umbrella_with_open_dep(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """One dep done, one in_progress — must NOT retire."""
    session, board, lead, worker = seeded
    dep_done = _make_dep(board_id=board.id, worker_id=worker.id, status="done")
    dep_open = _make_dep(board_id=board.id, worker_id=worker.id, status="in_progress")
    umbrella = _make_umbrella(board_id=board.id, lead_id=lead.id)
    session.add(dep_done)
    session.add(dep_open)
    session.add(umbrella)
    session.add(
        TaskDependency(
            board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep_done.id
        ),
    )
    session.add(
        TaskDependency(
            board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep_open.id
        ),
    )
    _seed_marker(session, board_id=board.id, task_id=umbrella.id, agent_id=lead.id)
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)

    assert retired == []
    await session.refresh(umbrella)
    assert umbrella.status == "inbox"


@pytest.mark.asyncio
async def test_sweep_skips_umbrella_with_open_parent_task_id_child(
    seeded: tuple[AsyncSession, Board, Agent, Agent],
) -> None:
    """All deps terminal + marker present, BUT the umbrella has an
    in-progress parent_task_id child — not a pure container; skip."""
    session, board, lead, worker = seeded
    dep = _make_dep(board_id=board.id, worker_id=worker.id, status="done")
    umbrella = _make_umbrella(board_id=board.id, lead_id=lead.id)
    session.add(dep)
    session.add(umbrella)
    session.add(
        TaskDependency(
            board_id=board.id, task_id=umbrella.id, depends_on_task_id=dep.id
        ),
    )
    _seed_marker(session, board_id=board.id, task_id=umbrella.id, agent_id=lead.id)
    open_child = Task(
        id=uuid4(),
        board_id=board.id,
        parent_task_id=umbrella.id,
        title="Open child",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=datetime(2026, 5, 5, 0, 0),
    )
    session.add(open_child)
    await session.commit()

    retired = await auto_retire_pure_container_umbrellas(session, board_id=board.id)

    assert retired == []
    await session.refresh(umbrella)
    assert umbrella.status == "inbox"
