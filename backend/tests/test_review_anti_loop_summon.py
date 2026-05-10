# ruff: noqa: INP001
"""Anti-loop early-summon: the SECOND consecutive FAIL/INCONCLUSIVE on a
task with the same target should auto-post an `@Architect` summon comment
quoting the repeat failure, BEFORE the existing FAIL #4 anti-loop blocker
threshold fires.

Production gap 2026-05-06 on task `e4738a7c` (E.02 Responsive 4×3 matrix):
PF burned four QA-FAIL cycles attacking the wrong CSS selector before
the operator manually summoned Architect for root-cause measurement. The
4× rule was already flagged by Supervisor as the blocker SUMMARY at FAIL
#4, but by then ~2 hours of PF time was gone. Triggering the soft-summon
at FAIL #2 (when the failure is genuinely repeating on the same scope)
catches selector-misdiagnosis early without paging Architect for normal
first-fix misses.

The matching signal: same `target` field across two consecutive
non-PASS verdicts. The same target proves it's the same scope; a worker
fixing one issue and exposing a different one would change the target.

These tests are RED until the auto-summon hook is wired into
`record_task_review_event`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.task_review_events import TaskReviewEventCreate


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


async def _seed_frontend_ui_task(
    sqlite_session: AsyncSession, *, slug: str
) -> tuple[Board, Agent, Task]:
    """Seed an org/gateway/board with a QA-E2E agent and a frontend_ui
    task currently in `review` status."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    qa_id = uuid4()
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
    qa = Agent(
        id=qa_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="QA-E2E",
        openclaw_session_id=f"agent:{slug}:qa",
    )
    sqlite_session.add(qa)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{slug}",
        status="review",
        review_packet_type="frontend_ui",
        assigned_agent_id=qa_id,
        packet_commit_sha="0123abc",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    return board, qa, task


async def _post_fail(
    session: AsyncSession,
    *,
    task: Task,
    actor: Agent,
    target: str,
    note: str = "",
) -> None:
    """Post a structured FAIL review event."""
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="fail",
        evidence_type="browser",
        target=target,
        evidence={"comment": note or "QA-E2E FAIL: layout regression"},
    )
    await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=session,
        actor=_ActorStub(agent=actor),  # type: ignore[arg-type]
    )
    # The auto-rework on FAIL transitions the task; restage to review
    # for the next cycle so we can simulate a repeat-FAIL streak.
    task.status = "review"
    task.in_progress_at = None
    task.rework_started_at = None
    session.add(task)
    await session.commit()
    await session.refresh(task)


@pytest.mark.asyncio
async def test_second_consecutive_fail_same_target_summons_architect(
    sqlite_session: AsyncSession,
) -> None:
    """FAIL #2 with the same `target` as FAIL #1 must auto-post an
    `@Architect` summon comment before any further iteration."""
    board, qa, task = await _seed_frontend_ui_task(sqlite_session, slug="loop-soft")
    target = "http://192.168.2.63:3002/product#mobile-overflow"

    await _post_fail(
        sqlite_session,
        task=task,
        actor=qa,
        target=target,
        note="FAIL #1: scrollWidth=363 > clientWidth=343 on /product mobile",
    )
    await _post_fail(
        sqlite_session,
        task=task,
        actor=qa,
        target=target,
        note="FAIL #2: same overflow still present after fix #1",
    )

    # Soft-summon comment must exist tagging Architect.
    rows = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == task.id)
            .where(col(ActivityEvent.event_type) == "task.anti_loop_summon"),
        ),
    )
    assert len(rows) >= 1, (
        "expected at least one task.anti_loop_summon activity event after "
        "two consecutive FAILs on the same target"
    )
    msg = rows[0].message or ""
    assert "@Architect" in msg, f"summon comment must tag @Architect; got: {msg!r}"
    assert (
        "FAIL #2" in msg or "second consecutive" in msg.lower()
    ), f"summon comment must call out the repeat-failure pattern; got: {msg!r}"


@pytest.mark.asyncio
async def test_second_fail_different_target_does_not_summon(
    sqlite_session: AsyncSession,
) -> None:
    """If the second FAIL cites a DIFFERENT target than the first, the
    iteration is not stuck — the worker fixed one issue and exposed
    another. No summon should fire."""
    board, qa, task = await _seed_frontend_ui_task(sqlite_session, slug="loop-different-target")
    await _post_fail(
        sqlite_session,
        task=task,
        actor=qa,
        target="http://192.168.2.63:3002/product#mobile-overflow",
        note="FAIL #1: /product mobile overflow",
    )
    await _post_fail(
        sqlite_session,
        task=task,
        actor=qa,
        target="http://192.168.2.63:3002/docs#tablet-spacing",
        note="FAIL #2: docs tablet spacing",
    )

    rows = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == task.id)
            .where(col(ActivityEvent.event_type) == "task.anti_loop_summon"),
        ),
    )
    assert rows == [], (
        f"summon must NOT fire when consecutive FAILs cite different targets; "
        f"got {len(rows)} summon events"
    )


@pytest.mark.asyncio
async def test_pass_resets_anti_loop_streak(
    sqlite_session: AsyncSession,
) -> None:
    """A PASS verdict between FAILs resets the streak; a subsequent
    FAIL is the new FAIL #1, not FAIL #2-of-the-prior-streak."""
    board, qa, task = await _seed_frontend_ui_task(sqlite_session, slug="loop-pass-reset")
    target = "http://192.168.2.63:3002/product#mobile-overflow"

    await _post_fail(sqlite_session, task=task, actor=qa, target=target, note="FAIL #1")
    # PASS verdict between FAILs. Seed directly to dodge the
    # qa_e2e_pass_invalid_evidence gate (this test is about streak
    # reset behavior, not evidence-completeness invariants — those
    # are covered in test_review_event_artifact_invariant.py).
    from app.models.task_review_events import TaskReviewEvent

    sqlite_session.add(
        TaskReviewEvent(
            board_id=board.id,
            task_id=task.id,
            agent_id=qa.id,
            reviewer_role="qa_e2e",
            verdict="pass",
            evidence_type="browser",
            target=target,
            evidence={"comment": "PASS reset (test stub)"},
        ),
    )
    await sqlite_session.commit()
    # New cycle starts; this is FAIL #1 of a new streak, not FAIL #2.
    await _post_fail(
        sqlite_session, task=task, actor=qa, target=target, note="new FAIL after a PASS"
    )

    rows = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == task.id)
            .where(col(ActivityEvent.event_type) == "task.anti_loop_summon"),
        ),
    )
    assert rows == [], (
        f"summon must NOT fire when PASS reset the streak between FAILs; "
        f"got {len(rows)} summon events"
    )


@pytest.mark.asyncio
async def test_third_consecutive_fail_files_anti_loop_blocker(
    sqlite_session: AsyncSession,
) -> None:
    """FAIL #3 on the same target must file a structured anti-loop
    Blocker (hard halt requiring operator/Architect adjudication),
    so the worker stops iterating and the operator sees a parked
    signal in `review-readiness.artifact_issues`."""
    board, qa, task = await _seed_frontend_ui_task(sqlite_session, slug="loop-hard-halt")
    target = "http://192.168.2.63:3002/product#mobile-overflow"
    for i in (1, 2, 3):
        await _post_fail(
            sqlite_session,
            task=task,
            actor=qa,
            target=target,
            note=f"FAIL #{i}: same selector still wrong",
        )

    blockers = list(
        await sqlite_session.exec(
            select(Blocker)
            .where(col(Blocker.task_id) == task.id)
            .where(col(Blocker.reason_code) == "review_anti_loop"),
        ),
    )
    assert len(blockers) >= 1, (
        "expected at least one review_anti_loop Blocker after FAIL #3 " "on the same target"
    )


@pytest.mark.asyncio
async def test_summon_idempotent_within_same_streak(
    sqlite_session: AsyncSession,
) -> None:
    """Once a summon has fired for an active streak, FAIL #3 on the
    same scope must NOT post a second summon comment — the original
    summon is still authoritative; FAIL #3 produces the Blocker
    instead. Avoids comment spam on a stuck loop."""
    board, qa, task = await _seed_frontend_ui_task(sqlite_session, slug="loop-summon-idempotent")
    target = "http://192.168.2.63:3002/product#mobile-overflow"
    await _post_fail(sqlite_session, task=task, actor=qa, target=target, note="#1")
    await _post_fail(sqlite_session, task=task, actor=qa, target=target, note="#2")
    await _post_fail(sqlite_session, task=task, actor=qa, target=target, note="#3")

    summons = list(
        await sqlite_session.exec(
            select(ActivityEvent)
            .where(col(ActivityEvent.task_id) == task.id)
            .where(col(ActivityEvent.event_type) == "task.anti_loop_summon"),
        ),
    )
    assert (
        len(summons) == 1
    ), f"expected exactly one summon event per active streak; got {len(summons)}"
