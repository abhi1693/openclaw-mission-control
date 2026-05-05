# ruff: noqa: INP001
"""Pure-container umbrellas (depends_on edges, no parent_task_id children)
must auto-retire when their last unresolved dep clears.

Today, ``maybe_cascade_umbrella_close`` only walks parent_task_id-edges:
it requires the candidate parent to have non-empty
``parent_task_id``-children all in TERMINAL_STATUSES. Umbrellas connected
to their executable work via ``depends_on_task_ids`` (instead of
``parent_task_id``) — what Supervisor calls "pure containers" — never
qualify. They sit inbox forever, even when:
  - All depends_on are done/cancelled.
  - Lead has posted the explicit UMBRELLA_RETIRED marker comment.
  - Architect has confirmed no_child_tasks_required=true.
  - The umbrella itself never executed.

This is the same retirement intent as the parent_task_id cascade — just
a different graph edge. From the lead's perspective, both shapes mean
"this container has nothing left to track; cancel it".

These tests are RED until the new helper
``maybe_retire_pure_container_umbrella`` is wired into the
dep-cleared path in ``_reconcile_dependents_for_dependency_toggle``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.tasks import _reconcile_dependents_for_dependency_toggle
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task, Task, Agent, Agent]]:
    """Seed: pure-container umbrella `umbrella_task` with depends_on -> dep_task.
    dep_task has just transitioned in_progress -> done.
    Returns (session, board, dep_task, umbrella_task, lead, worker).
    """
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()
    dep_id = uuid4()
    umbrella_id = uuid4()

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
        name="pure-container retire board",
        slug="pure-container-retire",
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
    dep_task = Task(
        id=dep_id,
        board_id=board_id,
        title="Executable QA gate (just done)",
        status="done",
        assigned_agent_id=worker_id,
        in_progress_at=datetime(2026, 5, 5, 0, 0),
    )
    umbrella_task = Task(
        id=umbrella_id,
        board_id=board_id,
        title="Pure-container umbrella",
        status="inbox",
        assigned_agent_id=lead_id,
        # never-executed: in_progress_at and previous_in_progress_at both None
    )
    sqlite_session.add(dep_task)
    sqlite_session.add(umbrella_task)
    sqlite_session.add(
        TaskDependency(
            board_id=board_id,
            task_id=umbrella_id,
            depends_on_task_id=dep_id,
        ),
    )
    await sqlite_session.commit()
    await sqlite_session.refresh(dep_task)
    await sqlite_session.refresh(umbrella_task)
    yield sqlite_session, board, dep_task, umbrella_task, lead, worker


def _seed_umbrella_retired_marker(
    session: AsyncSession, *, board_id, task_id, agent_id
) -> None:
    """Emulate the lead posting the canonical UMBRELLA_RETIRED comment."""
    session.add(
        ActivityEvent(
            board_id=board_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type="task.comment",
            message=(
                "UMBRELLA_RETIRED — pure-container closure disposition accepted.\n"
                "Architect posted no_child_tasks_required=true; no new subtasks required."
            ),
        ),
    )


async def _trigger_dep_clear(
    session: AsyncSession, *, board: Board, dep_task: Task, worker: Agent
) -> None:
    """Drive the production dep-clear path."""
    await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=board.id,
        dependency_task=dep_task,
        previous_status="in_progress",
        actor_agent_id=worker.id,
    )
    await session.commit()


@pytest.mark.asyncio
async def test_pure_container_umbrella_auto_retired_when_last_dep_clears(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
) -> None:
    """All retirement preconditions met: marker present, never-executed,
    only dep just transitioned to done. Umbrella must auto-cancel."""
    session, board, dep_task, umbrella_task, lead, worker = seeded
    _seed_umbrella_retired_marker(
        session, board_id=board.id, task_id=umbrella_task.id, agent_id=lead.id
    )
    await session.commit()

    await _trigger_dep_clear(session, board=board, dep_task=dep_task, worker=worker)

    await session.refresh(umbrella_task)
    assert umbrella_task.status == "cancelled", (
        f"expected pure-container umbrella to auto-cancel after last dep "
        f"cleared; status={umbrella_task.status}"
    )
    assert umbrella_task.cancelled_at is not None


@pytest.mark.asyncio
async def test_pure_container_umbrella_not_retired_without_marker(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
) -> None:
    """Safety: no UMBRELLA_RETIRED marker comment → must NOT auto-cancel.
    The marker is the only reliable discriminator between a retired
    container and a legitimate unstarted task waiting on its
    prerequisite dep."""
    session, board, dep_task, umbrella_task, _lead, worker = seeded

    await _trigger_dep_clear(session, board=board, dep_task=dep_task, worker=worker)

    await session.refresh(umbrella_task)
    assert umbrella_task.status == "inbox", (
        f"expected umbrella to stay inbox without marker; "
        f"status={umbrella_task.status}"
    )


@pytest.mark.asyncio
async def test_pure_container_umbrella_not_retired_when_already_executed(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
) -> None:
    """Marker present but the umbrella was previously moved to in_progress
    (in_progress_at is not None) → NOT a pure container; do not auto-cancel."""
    session, board, dep_task, umbrella_task, lead, worker = seeded
    _seed_umbrella_retired_marker(
        session, board_id=board.id, task_id=umbrella_task.id, agent_id=lead.id
    )
    umbrella_task.in_progress_at = datetime(2026, 5, 4, 12, 0)
    session.add(umbrella_task)
    await session.commit()

    await _trigger_dep_clear(session, board=board, dep_task=dep_task, worker=worker)

    await session.refresh(umbrella_task)
    assert umbrella_task.status == "inbox", (
        f"expected umbrella to stay inbox when previously executed; "
        f"status={umbrella_task.status}"
    )


@pytest.mark.asyncio
async def test_pure_container_umbrella_not_retired_when_other_dep_open(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
) -> None:
    """Marker present but a second dep is still in_progress → still
    blocked; must NOT auto-cancel."""
    session, board, dep_task, umbrella_task, lead, worker = seeded
    _seed_umbrella_retired_marker(
        session, board_id=board.id, task_id=umbrella_task.id, agent_id=lead.id
    )
    second_dep = Task(
        id=uuid4(),
        board_id=board.id,
        title="Second dep — still in_progress",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=datetime(2026, 5, 5, 0, 0),
    )
    session.add(second_dep)
    session.add(
        TaskDependency(
            board_id=board.id,
            task_id=umbrella_task.id,
            depends_on_task_id=second_dep.id,
        ),
    )
    await session.commit()

    await _trigger_dep_clear(session, board=board, dep_task=dep_task, worker=worker)

    await session.refresh(umbrella_task)
    assert umbrella_task.status == "inbox", (
        f"expected umbrella to stay inbox while another dep is open; "
        f"status={umbrella_task.status}"
    )


@pytest.mark.asyncio
async def test_pure_container_umbrella_not_retired_with_open_parent_task_id_child(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
) -> None:
    """Marker present, all deps cleared, BUT the umbrella also has a
    non-terminal parent_task_id child → not actually a pure container;
    must NOT auto-cancel via the dep-clear path."""
    session, board, dep_task, umbrella_task, lead, worker = seeded
    _seed_umbrella_retired_marker(
        session, board_id=board.id, task_id=umbrella_task.id, agent_id=lead.id
    )
    open_child = Task(
        id=uuid4(),
        board_id=board.id,
        parent_task_id=umbrella_task.id,
        title="In-progress child of the umbrella",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=datetime(2026, 5, 5, 0, 0),
    )
    session.add(open_child)
    await session.commit()

    await _trigger_dep_clear(session, board=board, dep_task=dep_task, worker=worker)

    await session.refresh(umbrella_task)
    assert umbrella_task.status == "inbox", (
        f"expected umbrella to stay inbox while a non-terminal child remains; "
        f"status={umbrella_task.status}"
    )
