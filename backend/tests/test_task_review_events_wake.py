# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.task_review_events import TaskReviewEventCreate
from app.services.openclaw.gateway_rpc import GatewayConfig


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


@pytest.mark.asyncio
async def test_record_task_review_event_wakes_board_lead_after_commit(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    reviewer_id = uuid4()
    task_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{org_id}"))
    sqlite_session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Review wake board",
        slug="review-wake-board",
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
    reviewer = Agent(
        id=reviewer_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id="agent:architect:main",
        identity_profile={"role": "System Architect and Code Reviewer"},
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Task needing review event wake",
        status="review",
    )
    sqlite_session.add(lead)
    sqlite_session.add(reviewer)
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)

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

    monkeypatch.setattr(tasks_api, "GatewayDispatchService", _FakeDispatch)

    read = await tasks_api.record_task_review_event(
        payload=TaskReviewEventCreate(
            reviewer_role="architect",
            verdict="pass",
            evidence_type="source_review",
            evidence={"comment": "Source review passed"},
        ),
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=reviewer),
    )

    assert read.verdict == "pass"
    assert len(sent) == 1
    assert sent[0]["session_key"] == "agent:lead:main"
    assert sent[0]["agent_name"] == "Supervisor"
    assert sent[0]["deliver"] is True
    assert str(task.id) in str(sent[0]["message"])
    assert "structured review event" in str(sent[0]["message"]).lower()


@pytest.mark.asyncio
async def test_record_task_review_event_records_failed_lead_wake_without_failing(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    reviewer_id = uuid4()
    task_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{org_id}"))
    sqlite_session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Review wake failure board",
        slug="review-wake-failure-board",
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
    reviewer = Agent(
        id=reviewer_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id="agent:architect:main",
        identity_profile={"role": "System Architect and Code Reviewer"},
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Task with failed review wake",
        status="review",
    )
    sqlite_session.add(lead)
    sqlite_session.add(reviewer)
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)

    class _FailingDispatch:
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
            return "gateway closed"

    monkeypatch.setattr(tasks_api, "GatewayDispatchService", _FailingDispatch)

    read = await tasks_api.record_task_review_event(
        payload=TaskReviewEventCreate(
            reviewer_role="architect",
            verdict="pass",
            evidence_type="source_review",
            evidence={"comment": "Source review passed"},
        ),
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=reviewer),
    )

    assert read.verdict == "pass"

    activities = (
        await sqlite_session.exec(
            select(ActivityEvent).where(
                ActivityEvent.event_type == "review_event.lead_notify_failed",
            ),
        )
    ).all()
    assert len(activities) == 1
    assert "gateway closed" in (activities[0].message or "")


@pytest.mark.asyncio
async def test_record_task_review_event_fail_auto_transitions_review_to_rework(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase V §I9: Architect/QA FAIL on a task in ``review`` must
    auto-transition the task to ``rework`` so the failure surfaces in
    lead routing. AC5 incident at 2026-05-02 01:48 UTC repro: an
    Architect FAIL only flipped readiness non-ready, leaving the task
    stuck in ``review`` with the failure invisible to the lead drain
    loop. Side effects mirror the lead-path rework branch:
    ``rework_started_at`` is stamped, ``in_progress_at`` is snapshotted
    and cleared, ``rework_entry_commit_sha`` captures the failed
    packet, and the assignee is routed back to the worker who moved
    the task to review (the implementer, not the reviewer).
    """
    from datetime import datetime, timezone

    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()
    reviewer_id = uuid4()
    task_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{org_id}"))
    sqlite_session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    sqlite_session.add(
        Board(
            id=board_id,
            organization_id=org_id,
            gateway_id=gateway_id,
            name="Auto rework board",
            slug="auto-rework-board",
        ),
    )
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
        openclaw_session_id="agent:pf:main",
    )
    reviewer = Agent(
        id=reviewer_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id="agent:architect:main",
        identity_profile={"role": "System Architect and Code Reviewer"},
    )
    sqlite_session.add(lead)
    sqlite_session.add(worker)
    sqlite_session.add(reviewer)
    # Project convention is naive UTC (see app/core/time.py:as_naive_utc).
    in_progress_anchor = datetime(2026, 5, 2, 0, 30)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="AC5 — Render approved stats + trust-line",
        status="review",
        in_progress_at=in_progress_anchor,
        packet_commit_sha="2717681",
    )
    sqlite_session.add(task)
    # Worker moved this task to review earlier — that's how
    # _last_worker_who_moved_task_to_review attributes the
    # implementer for rework reassignment.
    sqlite_session.add(
        ActivityEvent(
            event_type="task.status_changed",
            message="Task moved to review: AC5 — Render approved stats + trust-line.",
            agent_id=worker_id,
            task_id=task_id,
            board_id=board_id,
        ),
    )
    await sqlite_session.commit()
    await sqlite_session.refresh(task)

    class _NoopDispatch:
        def __init__(self, session):
            self.session = session

        async def optional_gateway_config_for_board(self, board):
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(self, **kwargs):
            return None

    monkeypatch.setattr(tasks_api, "GatewayDispatchService", _NoopDispatch)

    read = await tasks_api.record_task_review_event(
        payload=TaskReviewEventCreate(
            reviewer_role="architect",
            verdict="fail",
            evidence_type="source_review",
            evidence={"comment": "Avatar dots residue conflicts with AC1 truth packet"},
        ),
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=reviewer),
    )

    assert read.verdict == "fail"

    await sqlite_session.refresh(task)
    assert task.status == "rework"
    assert task.assigned_agent_id == worker_id
    assert task.rework_started_at is not None
    assert task.rework_entry_commit_sha == "2717681"
    assert task.in_progress_at is None
    assert task.previous_in_progress_at == in_progress_anchor

    auto_status_events = (
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(ActivityEvent.task_id == task_id)
            .where(ActivityEvent.event_type == "task.status_changed"),
        )
    ).all()
    rework_events = [
        e for e in auto_status_events
        if (e.message or "").startswith("Task moved to rework:")
    ]
    assert len(rework_events) == 1
    assert "auto-transition" in (rework_events[0].message or "")


@pytest.mark.asyncio
async def test_record_task_review_event_fail_does_not_transition_when_status_not_review(
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-rework only fires when the task is currently in ``review``.
    A FAIL on an already-rework or in_progress task must not cascade
    further status changes — the lead/agent path owns those.
    """
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    reviewer_id = uuid4()
    task_id = uuid4()

    sqlite_session.add(Organization(id=org_id, name=f"org-{org_id}"))
    sqlite_session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    sqlite_session.add(
        Board(
            id=board_id,
            organization_id=org_id,
            gateway_id=gateway_id,
            name="Already rework board",
            slug="already-rework-board",
        ),
    )
    lead = Agent(
        id=lead_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Supervisor",
        is_board_lead=True,
        openclaw_session_id="agent:lead:main",
    )
    reviewer = Agent(
        id=reviewer_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id="agent:architect:main",
        identity_profile={"role": "System Architect and Code Reviewer"},
    )
    sqlite_session.add(lead)
    sqlite_session.add(reviewer)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Task already in rework",
        status="rework",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)

    class _NoopDispatch:
        def __init__(self, session):
            self.session = session

        async def optional_gateway_config_for_board(self, board):
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(self, **kwargs):
            return None

    monkeypatch.setattr(tasks_api, "GatewayDispatchService", _NoopDispatch)

    await tasks_api.record_task_review_event(
        payload=TaskReviewEventCreate(
            reviewer_role="architect",
            verdict="fail",
            evidence_type="source_review",
            evidence={"comment": "Re-fail on already-rework task"},
        ),
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=reviewer),
    )

    await sqlite_session.refresh(task)
    assert task.status == "rework"  # unchanged
    auto_events = (
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(ActivityEvent.task_id == task_id)
            .where(ActivityEvent.event_type == "task.status_changed"),
        )
    ).all()
    assert len(auto_events) == 0  # no auto-transition fired
