# ruff: noqa: INP001
"""Dependency-clearing must wake the board lead, symmetric to blocker resolve.

When task B depends_on task A and A transitions to ``done``, B's
``is_blocked`` flips False at the read layer. Today, the dependency-cleared
branch in ``_reconcile_dependents_for_dependency_toggle`` only writes a
``task.updated`` activity event — it does not wake the lead. So the
dependent silently becomes actionable but stays in inbox until the next
heartbeat tick "discovers" it.

This is asymmetric with ``update_task_blocker`` and the auto-resolve paths,
which already call ``notify_lead_after_blocker_resolved`` when the last
open Blocker on a task closes. From the lead's perspective, "last
unresolved dep just cleared" and "last open blocker just resolved" are
the same actionable signal.

These tests are RED until the wake fires on the dependency-cleared path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.tasks import _reconcile_dependents_for_dependency_toggle
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.services.lead_notify import notify_lead_after_dependency_cleared
from app.services.openclaw.gateway_rpc import GatewayConfig


async def _reconcile_then_wake(
    session: AsyncSession,
    *,
    board_id,
    dependency_task: Task,
    previous_status: str,
    actor_agent_id,
) -> list[Task]:
    """Mirror the production callsite contract: reconcile returns the
    list of newly-unblocked dependents, caller commits, then iterates
    the list and calls notify_lead_after_dependency_cleared for each."""
    newly_unblocked = await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=board_id,
        dependency_task=dependency_task,
        previous_status=previous_status,
        actor_agent_id=actor_agent_id,
    )
    await session.commit()
    for dependent in newly_unblocked:
        await notify_lead_after_dependency_cleared(
            session=session, task=dependent, dependency_task=dependency_task
        )
    return newly_unblocked


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task, Task, Agent, Agent]]:
    """Seed org/gateway/board + lead + worker + dep + dependent task.

    Returns: (session, board, dep_task, dependent_task, lead, worker).
    `dep_task` is the dependency that already moved to done before the
    test calls reconcile (with previous_status='in_progress').
    `dependent_task` depends_on dep_task; status=inbox; assigned to lead.
    """
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()
    dep_id = uuid4()
    dependent_id = uuid4()

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
        name="dep-clear wake board",
        slug="dep-clear-wake",
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
        title="Dependency task (just transitioned to done)",
        status="done",
        assigned_agent_id=worker_id,
        in_progress_at=datetime(2026, 5, 5, 0, 0),
    )
    dependent_task = Task(
        id=dependent_id,
        board_id=board_id,
        title="Real task waiting on dep (not an umbrella)",
        status="inbox",
        assigned_agent_id=lead_id,
    )
    sqlite_session.add(dep_task)
    sqlite_session.add(dependent_task)
    sqlite_session.add(
        TaskDependency(
            board_id=board_id,
            task_id=dependent_id,
            depends_on_task_id=dep_id,
        ),
    )
    await sqlite_session.commit()
    await sqlite_session.refresh(dep_task)
    await sqlite_session.refresh(dependent_task)
    yield sqlite_session, board, dep_task, dependent_task, lead, worker


def _patch_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Patch GatewayDispatchService inside lead_notify so wake calls are
    captured rather than dispatched. Both wake helpers (blocker_resolved
    and dependency_cleared) construct GatewayDispatchService inside
    lead_notify, so a single patch covers both."""
    sent: list[dict[str, object]] = []

    class _FakeDispatch:
        def __init__(self, _session: AsyncSession) -> None:
            pass

        async def optional_gateway_config_for_board(self, _board: Board) -> GatewayConfig:
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(
            self,
            *,
            session_key: str,
            config: GatewayConfig,
            agent_name: str,
            message: str,
            deliver: bool,
        ) -> None:
            sent.append(
                {
                    "session_key": session_key,
                    "agent_name": agent_name,
                    "message": message,
                    "deliver": deliver,
                }
            )
            return None

    import app.services.lead_notify as lead_notify

    monkeypatch.setattr(lead_notify, "GatewayDispatchService", _FakeDispatch)
    return sent


@pytest.mark.asyncio
async def test_dependency_cleared_wakes_lead_when_dependent_now_actionable(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dep just transitioned to done. Dependent has no other unresolved
    deps and no open Blockers, so it's now fully actionable. The lead
    must wake — symmetric with notify_lead_after_blocker_resolved."""
    session, board, dep_task, _dependent_task, _lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    await _reconcile_then_wake(
        session,
        board_id=board.id,
        dependency_task=dep_task,
        previous_status="in_progress",
        actor_agent_id=worker.id,
    )

    assert any("DEPENDENCY_CLEARED" in str(s.get("message", "")) for s in sent), (
        f"expected lead wake after last dep cleared; messages: "
        f"{[str(s.get('message',''))[:120] for s in sent]}"
    )


@pytest.mark.asyncio
async def test_dependency_cleared_no_wake_when_dependent_has_other_open_dep(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the dependent still has another unresolved dep, the wake must
    NOT fire — the task is still blocked; waking would be premature."""
    session, board, dep_task, dependent_task, _lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

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
            task_id=dependent_task.id,
            depends_on_task_id=second_dep.id,
        ),
    )
    await session.commit()

    await _reconcile_then_wake(
        session,
        board_id=board.id,
        dependency_task=dep_task,
        previous_status="in_progress",
        actor_agent_id=worker.id,
    )

    assert not any(
        "DEPENDENCY_CLEARED" in str(s.get("message", "")) for s in sent
    ), f"unexpected wake while another dep is still open: {sent}"


@pytest.mark.asyncio
async def test_dependency_cleared_no_wake_when_dependent_has_open_blocker(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the dependent has an open Blocker, the wake must NOT fire —
    the blocker still gates the task even though the dep cleared."""
    session, board, dep_task, dependent_task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    session.add(
        Blocker(
            id=uuid4(),
            board_id=board.id,
            task_id=dependent_task.id,
            category="operator",
            owner_role="operator",
            reason_code="operator_policy",
            created_by_agent_id=lead.id,
        ),
    )
    await session.commit()

    await _reconcile_then_wake(
        session,
        board_id=board.id,
        dependency_task=dep_task,
        previous_status="in_progress",
        actor_agent_id=worker.id,
    )

    assert not any(
        "DEPENDENCY_CLEARED" in str(s.get("message", "")) for s in sent
    ), f"unexpected wake while open Blocker remains on dependent: {sent}"


@pytest.mark.asyncio
async def test_dependency_cleared_no_wake_when_dependent_already_terminal(
    seeded: tuple[AsyncSession, Board, Task, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the dependent is already done/cancelled, no wake — the existing
    'if dependent.status == "done": continue' guard already skips it."""
    session, board, dep_task, dependent_task, _lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    dependent_task.status = "done"
    session.add(dependent_task)
    await session.commit()

    await _reconcile_then_wake(
        session,
        board_id=board.id,
        dependency_task=dep_task,
        previous_status="in_progress",
        actor_agent_id=worker.id,
    )

    assert not any(
        "DEPENDENCY_CLEARED" in str(s.get("message", "")) for s in sent
    ), f"unexpected wake against already-terminal dependent: {sent}"
