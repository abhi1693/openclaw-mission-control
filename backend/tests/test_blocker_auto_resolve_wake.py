# ruff: noqa: INP001
"""Auto-resolve paths must wake the board lead too.

Codex 2026-05-03 review caught: ``auto_resolve_pipeline_blockers_if_ready``
resolves Blockers WITHOUT going through ``update_task_blocker``, so the
lead-wake hook on the resolve PATCH never fires for those resolutions.
The exact "last open blocker just cleared" state can occur silently.

Two callers run auto-resolve:
- ``record_task_pipeline_event`` in ``app/api/tasks.py`` (forward race:
  worker posts the event that satisfies pipeline.ready)
- ``create_task_blocker`` in ``app/api/blockers.py`` (retroactive race:
  events already landed before the lead opened the Blocker)

Both must wake the lead when the auto-resolve closes the last open
Blocker on the task.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.api.blockers import create_task_blocker
from app.api.tasks import record_task_pipeline_event
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.blockers import BlockerCreate
from app.schemas.task_pipeline_events import TaskPipelineEventCreate
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
    """Seed org/gateway/board + lead + worker + an in_progress task."""
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
        name="auto-resolve wake board",
        slug="auto-resolve-wake",
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
        title="Task with auto-resolved pipeline blocker",
        status="in_progress",
        assigned_agent_id=worker_id,
        in_progress_at=datetime(2026, 5, 3, 0, 0),
        packet_commit_sha="abcdef0",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    yield sqlite_session, board, task, lead, worker


def _patch_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Install fake GatewayDispatchService that records sends. The wake
    helper imports GatewayDispatchService lazily inside its function body,
    so we patch at the SOURCE module (where the wake helper lives), not
    each caller. This single patch covers both auto-resolve sites."""
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

    # Patch the centralized wake helper module — both auto-resolve sites
    # call notify_lead_after_blocker_resolved which constructs
    # GatewayDispatchService inside lead_notify.
    import app.services.lead_notify as lead_notify
    monkeypatch.setattr(lead_notify, "GatewayDispatchService", _FakeDispatch)
    return sent


async def _post_full_pipeline(
    session: AsyncSession,
    *,
    task: Task,
    actor: Agent,
    commit_sha: str = "abcdef0",
    artifact_hash: str = "deadbeef",
    deploy_target: str = "http://192.168.2.63:3002",
    live_sha: str = "feedface",
) -> None:
    """Post the 6 events that make pipeline.ready=true. Last event
    triggers auto-resolve via record_task_pipeline_event."""
    states_with_payloads = [
        ("code_changed", {"commit_sha": commit_sha}),
        ("committed", {"commit_sha": commit_sha}),
        ("built", {"commit_sha": commit_sha, "artifact_hash": artifact_hash}),
        ("deployed", {"artifact_hash": artifact_hash, "deploy_target": deploy_target}),
        ("live_build_verified", {"deploy_target": deploy_target, "live_sha": live_sha}),
        ("runtime_verified", {"deploy_target": deploy_target, "evidence": {"qa": "ok"}}),
    ]
    for state, payload_kwargs in states_with_payloads:
        payload = TaskPipelineEventCreate(state=state, **payload_kwargs)
        await record_task_pipeline_event(
            payload=payload,
            task=task,
            session=session,
            actor=_ActorStub(agent=actor),
        )


@pytest.mark.asyncio
async def test_pipeline_event_auto_resolve_wakes_lead(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5-shape: lead opens pipeline_missing_review_gate Blocker, worker
    posts pipeline events that auto-resolve it. The auto-resolve must
    fire the lead wake (this was missing — caller of auto_resolve had
    no wake hook)."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    # Lead opens a system-authored pipeline blocker.
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
        created_by_agent_id=lead.id,
    )
    session.add(blocker)
    await session.commit()
    await session.refresh(blocker)

    # Worker posts the full pipeline. The 6th event triggers
    # auto_resolve_pipeline_blockers_if_ready, which closes the blocker.
    await _post_full_pipeline(session, task=task, actor=worker)

    await session.refresh(blocker)
    assert blocker.resolved_at is not None, "blocker should have auto-resolved"

    assert len(sent) >= 1, (
        f"expected lead wake after auto-resolve closed last open Blocker, "
        f"got {len(sent)} dispatches: {sent}"
    )
    # At least one dispatch must be the BLOCKER_RESOLVED wake.
    assert any("BLOCKER_RESOLVED" in str(s.get("message", "")) for s in sent), (
        f"expected at least one BLOCKER_RESOLVED wake; messages: "
        f"{[str(s.get('message',''))[:80] for s in sent]}"
    )


@pytest.mark.asyncio
async def test_blocker_create_retroactive_auto_resolve_wakes_lead(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retroactive race: worker posts events FIRST (T0), THEN lead opens
    the Blocker (T0+ε). create_task_blocker calls auto_resolve which
    immediately closes the brand-new Blocker. That auto-resolve must
    also wake the lead — same shape as the pipeline-event path."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    # Worker pre-posts the pipeline (no Blocker exists yet, so no wake
    # would fire from the pipeline path).
    await _post_full_pipeline(session, task=task, actor=worker)
    assert sent == [], "no Blocker exists yet, no wake expected"

    # Lead opens the system-authored pipeline Blocker. create_task_blocker
    # calls auto_resolve_pipeline_blockers_if_ready which immediately
    # resolves the just-created row.
    await create_task_blocker(
        payload=BlockerCreate.model_validate(
            {
                "category": "runtime",
                "owner_role": "Programmer-Frontend",
                "reason_code": "pipeline_missing_review_gate",
            },
        ),
        board=board,
        task=task,
        session=session,
        actor=_ActorStub(agent=lead),  # type: ignore[arg-type]
    )

    # Wake must fire because the just-created blocker auto-resolved AND
    # was the only one open on the task.
    assert any("BLOCKER_RESOLVED" in str(s.get("message", "")) for s in sent), (
        f"expected lead wake after retroactive auto-resolve; messages: "
        f"{[str(s.get('message',''))[:80] for s in sent]}"
    )


@pytest.mark.asyncio
async def test_pipeline_event_auto_resolve_no_wake_when_other_blockers_open(
    seeded: tuple[AsyncSession, Board, Task, Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wake is correct only when the auto-resolve closes the LAST open
    Blocker. If the task has another open Blocker (e.g. operator-policy)
    the wake would be premature — task is still blocked."""
    session, board, task, lead, worker = seeded
    sent = _patch_dispatch(monkeypatch)

    # Pipeline blocker (will auto-resolve)
    pipeline_blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
        created_by_agent_id=lead.id,
    )
    # Manual operator blocker (will NOT auto-resolve)
    operator_blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="operator",
        owner_role="operator",
        reason_code="operator_policy",
        created_by_agent_id=lead.id,
    )
    session.add(pipeline_blocker)
    session.add(operator_blocker)
    await session.commit()

    await _post_full_pipeline(session, task=task, actor=worker)
    await session.refresh(pipeline_blocker)
    await session.refresh(operator_blocker)
    assert pipeline_blocker.resolved_at is not None
    assert operator_blocker.resolved_at is None

    # The operator blocker is still open → no wake.
    assert not any("BLOCKER_RESOLVED" in str(s.get("message", "")) for s in sent), (
        f"unexpected wake while other open Blockers remain: {sent}"
    )
