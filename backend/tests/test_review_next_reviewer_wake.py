# ruff: noqa: INP001
"""Auto-wake the NEXT required reviewer after a PASS verdict.

Production gap 2026-05-06 across F.02, E.03, E.06, E.08: every Phase 3
review chain showed the same shape — Architect PASSes at T0, then
QA-E2E sits idle for 15-30 minutes until its next heartbeat tick
discovers the task. Total per-task gate latency: ~hour minimum, mostly
wake-discovery latency.

The fix: when a PASS arrives and review-readiness still has missing
required roles, the API actively wakes the agent matching the next
required role (gateway dispatch), the same way blocker-resolve and
dep-clear already wake the lead. A `task.next_reviewer_woken` activity
event is recorded for audit; subsequent PASS events for the same task
within the idempotency window don't re-wake.

Codex pushback (2026-05-06): the auto-wake must be safe under
concurrency — two PASS events from different roles arriving in quick
succession shouldn't both wake the same next reviewer (or a stale
next-reviewer pick). Idempotency is enforced via the activity-event
marker check inside the same transaction.

These tests are RED until the auto-wake hook is wired into
``record_task_review_event``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_review_events import TaskReviewEvent
from app.models.tasks import Task
from app.schemas.task_review_events import TaskReviewEventCreate
from app.services.openclaw.gateway_rpc import GatewayConfig


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


async def _seed_frontend_ui_board(
    sqlite_session: AsyncSession, *, slug: str
) -> tuple[Board, Agent, Agent, Agent, Task]:
    """Seed a frontend_ui task with Architect + QA-E2E agents on the
    board. Returns (board, architect, qa_e2e, lead, task)."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    architect_id = uuid4()
    qa_id = uuid4()
    lead_id = uuid4()
    task_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{slug}"))
    sqlite_session.add(
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
    sqlite_session.add(board)
    architect = Agent(
        id=architect_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id=f"agent:{slug}:architect",
        identity_profile={"dev_acp_flow": "review_only"},
    )
    qa_e2e = Agent(
        id=qa_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="QA-E2E",
        openclaw_session_id=f"agent:{slug}:qa-e2e",
    )
    lead = Agent(
        id=lead_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Supervisor",
        is_board_lead=True,
        openclaw_session_id=f"agent:{slug}:lead",
    )
    sqlite_session.add(architect)
    sqlite_session.add(qa_e2e)
    sqlite_session.add(lead)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{slug}",
        status="review",
        review_packet_type="frontend_ui",
        assigned_agent_id=architect_id,
        packet_commit_sha="abc1234",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    return board, architect, qa_e2e, lead, task


def _patch_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []

    class _FakeDispatch:
        def __init__(self, _session: AsyncSession) -> None:
            pass

        async def optional_gateway_config_for_board(self, _board: Board) -> GatewayConfig:
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

    import app.services.lead_notify as lead_notify

    monkeypatch.setattr(lead_notify, "GatewayDispatchService", _FakeDispatch)
    return sent


def _seed_pass_event(
    session: AsyncSession,
    *,
    task: Task,
    agent: Agent,
    role: str,
    target: str = "http://192.168.2.63:3002/",
) -> None:
    """Insert a PASS row directly to bypass evidence-completeness gates
    (those are exercised in test_review_event_artifact_invariant.py)."""
    session.add(
        TaskReviewEvent(
            board_id=task.board_id,
            task_id=task.id,
            agent_id=agent.id,
            reviewer_role=role,
            verdict="pass",
            evidence_type="source_review" if role == "architect" else "browser",
            target=target,
            evidence={"comment": "PASS test stub"},
        ),
    )


async def _post_architect_pass(
    session: AsyncSession,
    *,
    task: Task,
    architect: Agent,
    target: str = "http://192.168.2.63:3002/",
) -> None:
    """Post a real Architect PASS through the API path to exercise the
    next-reviewer wake hook."""
    # Seed a verdict comment with @lead citation (required by the
    # supervisor-citation invariant).
    session.add(
        ActivityEvent(
            event_type="task.comment",
            message="Architect PASS — @lead next gate is qa_e2e",
            task_id=task.id,
            board_id=task.board_id,
            agent_id=architect.id,
        ),
    )
    await session.commit()
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target=target,
        source_commit="abc1234",
        evidence={
            "comment": "Architect PASS",
            "no_child_tasks_required": True,
        },
    )
    await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=session,
        actor=_ActorStub(agent=architect),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_architect_pass_wakes_qa_e2e_on_frontend_ui(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """frontend_ui requires architect + qa_e2e. After Architect PASSes,
    the API must wake the QA-E2E agent (gateway dispatch) so it picks
    up the task before its next heartbeat tick."""
    board, architect, qa_e2e, lead, task = await _seed_frontend_ui_board(
        sqlite_session,
        slug="next-wake-arch-pass",
    )
    sent = _patch_dispatch(monkeypatch)

    await _post_architect_pass(sqlite_session, task=task, architect=architect)

    qa_wakes = [
        s
        for s in sent
        if s.get("session_key") == qa_e2e.openclaw_session_id
        and "NEXT_REVIEWER" in str(s.get("message", ""))
    ]
    assert len(qa_wakes) >= 1, (
        f"expected QA-E2E to receive a NEXT_REVIEWER wake after Architect PASS; "
        f"sent={[(s.get('agent_name'), str(s.get('message', ''))[:60]) for s in sent]}"
    )
    rows = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == task.id)
            .where(col(ActivityEvent.event_type) == "task.next_reviewer_woken"),
        ),
    )
    assert (
        len(rows) == 1
    ), f"expected exactly one task.next_reviewer_woken activity event; got {len(rows)}"


@pytest.mark.asyncio
async def test_no_wake_when_all_required_roles_passed(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the PASS that just landed completes ALL required roles,
    review-readiness is now ready=True and the existing lead-only wake
    handles routing. Don't double-wake any reviewer."""
    board, architect, qa_e2e, lead, task = await _seed_frontend_ui_board(
        sqlite_session,
        slug="next-wake-all-passed",
    )
    sent = _patch_dispatch(monkeypatch)
    # Pre-seed Architect PASS so this Architect call IS the first one
    # missing — wait, here we want Architect to be already passed and
    # QA-E2E PASS to be the FINAL one. Seed Architect PASS first.
    _seed_pass_event(sqlite_session, task=task, agent=architect, role="architect")
    await sqlite_session.commit()
    # Now post QA-E2E PASS via direct seed (avoids qa_e2e evidence gate)
    _seed_pass_event(sqlite_session, task=task, agent=qa_e2e, role="qa_e2e")
    await sqlite_session.commit()
    # Manually invoke the next-reviewer hook the same way the API would
    # after the QA-E2E PASS. Here we expect NO wake because all required
    # roles are now satisfied.
    fake_event = (
        await sqlite_session.exec(
            select(TaskReviewEvent)
            .where(col(TaskReviewEvent.task_id) == task.id)
            .where(col(TaskReviewEvent.reviewer_role) == "qa_e2e")
        )
    ).first()
    assert fake_event is not None
    from app.api.tasks import _wake_next_required_reviewer_after_pass

    await _wake_next_required_reviewer_after_pass(
        session=sqlite_session,
        task=task,
        latest_event=fake_event,
        actor_agent_id=qa_e2e.id,
    )

    next_wakes = [s for s in sent if "NEXT_REVIEWER" in str(s.get("message", ""))]
    assert next_wakes == [], f"unexpected NEXT_REVIEWER wake after final PASS; sent={sent}"


@pytest.mark.asyncio
async def test_idempotent_no_double_wake_for_same_role(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If two PASS events for Architect arrive on the same task in
    quick succession (e.g. retry, double-submit), only one QA-E2E
    wake should fire. Idempotency via activity-event marker check."""
    board, architect, qa_e2e, lead, task = await _seed_frontend_ui_board(
        sqlite_session,
        slug="next-wake-idempotent",
    )
    sent = _patch_dispatch(monkeypatch)

    await _post_architect_pass(sqlite_session, task=task, architect=architect)
    # Second Architect PASS — should NOT trigger another QA wake
    # because the marker activity event already exists.
    fake_event = (
        await sqlite_session.exec(
            select(TaskReviewEvent)
            .where(col(TaskReviewEvent.task_id) == task.id)
            .where(col(TaskReviewEvent.reviewer_role) == "architect")
            .order_by(col(TaskReviewEvent.created_at).desc())
        )
    ).first()
    assert fake_event is not None
    from app.api.tasks import _wake_next_required_reviewer_after_pass

    await _wake_next_required_reviewer_after_pass(
        session=sqlite_session,
        task=task,
        latest_event=fake_event,
        actor_agent_id=architect.id,
    )

    qa_wakes = [
        s
        for s in sent
        if s.get("session_key") == qa_e2e.openclaw_session_id
        and "NEXT_REVIEWER" in str(s.get("message", ""))
    ]
    assert len(qa_wakes) == 1, (
        f"expected exactly one QA-E2E NEXT_REVIEWER wake even with two "
        f"Architect PASS events; got {len(qa_wakes)}"
    )


@pytest.mark.asyncio
async def test_no_wake_when_no_agent_for_missing_role(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: if the board has no agent matching the required
    missing role (rare config error), the wake silently no-ops rather
    than crashing the PASS POST."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    architect_id = uuid4()
    task_id = uuid4()
    sqlite_session.add(Organization(id=org_id, name="org-noagent"))
    sqlite_session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gw-noagent",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="noagent",
        slug="noagent",
    )
    sqlite_session.add(board)
    architect = Agent(
        id=architect_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id="agent:noagent:architect",
        identity_profile={"dev_acp_flow": "review_only"},
    )
    sqlite_session.add(architect)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="noagent-task",
        status="review",
        review_packet_type="frontend_ui",  # requires architect + qa_e2e
        assigned_agent_id=architect_id,
        packet_commit_sha="def5678",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    sent = _patch_dispatch(monkeypatch)

    await _post_architect_pass(sqlite_session, task=task, architect=architect)

    qa_wakes = [s for s in sent if "NEXT_REVIEWER" in str(s.get("message", ""))]
    assert (
        qa_wakes == []
    ), f"unexpected NEXT_REVIEWER wake when no QA-E2E agent on board; sent={sent}"
