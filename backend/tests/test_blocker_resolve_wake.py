# ruff: noqa: INP001
"""Blocker resolution must wake the board lead.

Repro 2026-05-03: operator-policy Blocker on Track B (5f847e51) was
resolved at 16:35 UTC after operator confirmed OP-1 commitments. The
task ``is_blocked`` derivation correctly flipped from True to False,
but no wake notification fired — the assigned Architect and the lead
Supervisor stayed unaware. Track B sat unblocked-but-untouched in
inbox for 50+ minutes, holding up the entire downstream chain
(QA gate -> Phase 2 umbrella -> Phase 3 umbrella) on a 5-minute
heartbeat tick that nobody had reason to expect.

Symmetric to the review-event PASS path which DOES wake the next
reviewer/lead — Blocker resolution should wake the lead so the
drain loop picks up the newly-actionable task. Routing decision
stays with the lead (Supervisor); we don't bypass to the assignee
directly because the world may have changed since the Blocker was
filed (operator may want to re-route, decomposition may have
evolved, etc.).

Invariant pinned by these tests:
- ``status_transition=resolve`` PATCH on a task's last open Blocker
  triggers ``GatewayDispatchService.try_send_agent_message`` to the
  board lead with ``deliver=True``
- Resolution still succeeds when the lead wake fails (best-effort —
  same contract as ``_notify_lead_on_end_work_event`` in tasks.py)
- ``status_transition=acknowledge`` does NOT fire a wake (only the
  resolve transition is the "now actionable" signal)
- A task with multiple open Blockers does NOT fire wake until the
  LAST one resolves (otherwise the wake fires too early — the
  task is_blocked flip from the dep-graph happens only when zero
  Blockers remain)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.blockers as blockers_api
from app.api.blockers import create_task_blocker, update_task_blocker
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.blockers import BlockerCreate, BlockerUpdate
from app.services.openclaw.gateway_rpc import GatewayConfig


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task, Agent, Agent]]:
    """Seed org/gateway/board + a board lead + a worker + an in-progress task."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()
    task_id = uuid4()

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
        name="Blocker resolve wake board",
        slug="blocker-resolve-wake",
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
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Task with operator-policy blocker",
        status="inbox",
        assigned_agent_id=worker_id,
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    yield sqlite_session, board, task, lead, worker


def _patch_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Install a fake GatewayDispatchService that records sends. Returns
    the recorder list — use ``len(sent)`` to count wake invocations."""
    sent: list[dict[str, object]] = []

    class _FakeDispatch:
        def __init__(self, session):
            self.session = session

        async def optional_gateway_config_for_board(self, board):
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(
            self,
            *,
            session_key,
            config,
            agent_name,
            message,
            deliver,
        ):
            sent.append(
                {
                    "session_key": session_key,
                    "agent_name": agent_name,
                    "message": message,
                    "deliver": deliver,
                }
            )
            return None

    monkeypatch.setattr(blockers_api, "GatewayDispatchService", _FakeDispatch)
    return sent


@pytest.mark.asyncio
async def test_blocker_resolve_wakes_lead_when_last_open_blocker(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Track B repro: resolving the only open Blocker on a task must
    fire a lead wake so the drain loop picks the task up."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    created = await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {"category": "operator", "owner_role": "operator", "reason_code": "operator_policy"},
        ),
        board=board,
        task=task,
        session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )

    # No wake on Blocker create — only on resolve.
    assert sent == [], "create must not wake; only resolve does"

    resolved = await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task,
        session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    assert resolved.resolved_at is not None

    # Lead wake fired exactly once.
    assert len(sent) == 1, f"expected 1 lead wake, got {len(sent)}: {sent}"
    assert sent[0]["session_key"] == "agent:lead:main"
    assert sent[0]["agent_name"] == "Supervisor"
    assert sent[0]["deliver"] is True
    assert str(task.id) in str(sent[0]["message"]), \
        "wake message must reference the unblocked task id"


@pytest.mark.asyncio
async def test_blocker_acknowledge_does_not_wake_lead(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acknowledge is a soft signal (lead is now aware) but the task is
    still blocked — it must NOT fire a wake."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)
    created = await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {"category": "operator", "owner_role": "operator"},
        ),
        board=board,
        task=task,
        session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="acknowledge"),
        task=task,
        session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    assert sent == [], "acknowledge must not wake — task still blocked"


@pytest.mark.asyncio
async def test_blocker_resolve_no_wake_when_other_blockers_still_open(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If task has 2 open Blockers and we resolve only 1, the task is
    STILL blocked — no wake should fire (would be premature). Wake
    must only fire when the last open Blocker resolves and the task
    actually becomes actionable."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    a = await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {"category": "operator", "owner_role": "operator", "reason_code": "operator_policy"},
        ),
        board=board, task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    b = await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {"category": "source", "owner_role": "frontend-dev", "reason_code": "source_pending"},
        ),
        board=board, task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    assert sent == [], "creates must not wake"

    # Resolve only A — B is still open.
    await update_task_blocker(
        blocker_id=a.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    assert sent == [], "resolve must not wake while other Blockers remain open"

    # Resolve B — task becomes actionable, wake fires.
    await update_task_blocker(
        blocker_id=b.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    assert len(sent) == 1, "wake must fire exactly once on the LAST resolve"


@pytest.mark.asyncio
async def test_blocker_resolve_succeeds_when_lead_wake_fails(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort contract: notify failure must not roll back the
    Blocker resolution itself. Same contract as
    _notify_lead_on_end_work_event in tasks.py."""
    session, board, task, lead, worker = seeded

    class _BoomDispatch:
        def __init__(self, session):
            self.session = session

        async def optional_gateway_config_for_board(self, board):
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(self, **_kwargs):
            raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(blockers_api, "GatewayDispatchService", _BoomDispatch)

    created = await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {"category": "operator", "owner_role": "operator"},
        ),
        board=board, task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    resolved = await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task, session=session,
        actor=_ActorStub(agent=worker),  # type: ignore[arg-type]
    )
    # Resolution must persist despite the wake failure.
    assert resolved.resolved_at is not None
