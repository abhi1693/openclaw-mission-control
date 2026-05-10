# ruff: noqa: INP001
"""Pipeline-event POST must reject when ``task.status == "rework"``.

Repro from 2026-05-03 (E.3 ``f892fd65``): Programmer-Frontend posted six
``pipeline/events`` while the task was still in ``rework`` (200 OK on each
POST), then PATCHed ``rework → in_progress``. The cycle anchor reset to
the new ``in_progress_at``, and the previously-posted events fell *outside*
the new cycle window — silently invisible to ``pipeline.ready`` /
``auto_resolve_pipeline_blockers_if_ready``. PF had to repost the same six
events to refill the new cycle.

Cycle scope is load-bearing for Phase V §I9 Fix 2 (it prevents stale-event
auto-resolve, the inverse of the AC5 failure mode), so the cycle reset must
stay. The fix is to reject the POST upstream — surface the workflow
violation at the *first* offending event, not silently after five wasted
events. The error directs the agent to PATCH ``rework → in_progress``
first, which is the only ``_AGENT_PATH_VALID_TRANSITIONS`` predecessor
of the next ``review`` submission.

Invariant pinned by these tests:
- POST /pipeline/events while ``status="rework"`` returns 409 with
  ``code=pipeline_event_requires_in_progress``.
- Every other status keeps current permissive behavior — ``in_progress``,
  ``review``, ``done`` all still accept POSTs (the gate is narrow on
  purpose; broadening would cascade into late-deploy verification flows).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.task_pipeline_events import TaskPipelineEventCreate


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


async def _seed_task_with_status(
    session: AsyncSession,
    *,
    board_slug: str,
    status: str,
    in_progress_at: datetime | None = datetime(2026, 5, 3, 14, 30),
    previous_in_progress_at: datetime | None = None,
) -> tuple[Board, Agent, Task]:
    """Seed an org/gateway/board/worker + a task fixed at ``status``.

    Defaults match the E.3 repro shape: a task that was once in_progress
    (so ``previous_in_progress_at`` is set when status="rework") but is
    not currently in_progress.
    """
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    worker_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{board_slug}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{board_slug}",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name=board_slug,
        slug=board_slug,
    )
    session.add(board)
    worker = Agent(
        id=worker_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Programmer-Frontend",
        openclaw_session_id=f"agent:{board_slug}:worker",
    )
    session.add(worker)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{board_slug}",
        status=status,
        assigned_agent_id=worker_id,
        in_progress_at=in_progress_at,
        previous_in_progress_at=previous_in_progress_at,
        packet_commit_sha="abcdef0",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, worker, task


async def _attempt_post_event(
    session: AsyncSession,
    *,
    task: Task,
    actor: Agent,
    state: str = "code_changed",
    commit_sha: str | None = "abcdef0",
) -> None:
    payload = TaskPipelineEventCreate(state=state, commit_sha=commit_sha)
    await tasks_api.record_task_pipeline_event(
        payload=payload,
        task=task,
        session=session,
        actor=_ActorStub(agent=actor),
    )


@pytest.mark.asyncio
async def test_pipeline_event_post_rejected_when_task_status_is_rework(
    sqlite_session: AsyncSession,
) -> None:
    """E.3 repro: posting a pipeline event while ``status="rework"`` must
    fail fast with 409, not silently land an event that the next cycle
    will discard."""
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="rework-gate-409",
        status="rework",
        # E.3-shape: prior cycle ended (rework), no fresh in_progress yet.
        in_progress_at=None,
        previous_in_progress_at=datetime(2026, 5, 3, 14, 30),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _attempt_post_event(
            sqlite_session,
            task=task,
            actor=worker,
            state="code_changed",
        )

    assert exc_info.value.status_code == 409, (
        f"expected 409 Conflict on rework-state pipeline POST, " f"got {exc_info.value.status_code}"
    )
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured detail, got {type(detail).__name__}"
    assert (
        detail.get("code") == "pipeline_event_requires_in_progress"
    ), f"expected code=pipeline_event_requires_in_progress, got code={detail.get('code')!r}"
    # Message must mention rework + the corrective PATCH so agents can act on it.
    assert "rework" in str(detail.get("message", "")).lower()
    assert (
        "in_progress" in str(detail.get("message", "")).lower()
        or "in progress" in str(detail.get("message", "")).lower()
    )


@pytest.mark.asyncio
async def test_pipeline_event_post_allowed_when_task_status_is_in_progress(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: the gate must be narrow. ``in_progress`` is the
    canonical happy path and must keep accepting POSTs."""
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="rework-gate-in-progress-ok",
        status="in_progress",
    )
    # Should not raise.
    await _attempt_post_event(
        sqlite_session,
        task=task,
        actor=worker,
        state="code_changed",
    )


@pytest.mark.asyncio
async def test_pipeline_event_post_allowed_when_task_status_is_review(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: events can land mid-review (e.g. devops late
    runtime_verified). The gate is rework-only, not "any non-in_progress."
    """
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="rework-gate-review-ok",
        status="review",
    )
    await _attempt_post_event(
        sqlite_session,
        task=task,
        actor=worker,
        state="code_changed",
    )


@pytest.mark.asyncio
async def test_pipeline_event_post_allowed_when_task_status_is_done(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: late retroactive deploy events on done tasks
    must remain allowed (post-merge runtime verification flows)."""
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="rework-gate-done-ok",
        status="done",
    )
    await _attempt_post_event(
        sqlite_session,
        task=task,
        actor=worker,
        state="code_changed",
    )


@pytest.mark.asyncio
async def test_pipeline_event_post_rejected_when_task_status_is_inbox(
    sqlite_session: AsyncSession,
) -> None:
    """Inbox tasks have no in_progress cycle anchor — same cycle-anchor
    bug as rework. Posting events here lumps them under None/null and
    the next cycle reset silently discards them. Reject upstream so
    the agent transitions inbox → in_progress first."""
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="gate-inbox-rejected",
        status="inbox",
        in_progress_at=None,
        previous_in_progress_at=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _attempt_post_event(
            sqlite_session,
            task=task,
            actor=worker,
            state="code_changed",
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pipeline_event_requires_in_progress"
    assert detail.get("current_status") == "inbox"


@pytest.mark.asyncio
async def test_pipeline_event_post_rejected_when_task_status_is_cancelled(
    sqlite_session: AsyncSession,
) -> None:
    """Cancelled tasks are dead — posting new pipeline events on them
    is suspect at best (retroactive evidence on abandoned work). Reject
    so the agent doesn't accidentally pollute audit trails on tasks
    that operator/lead has explicitly removed from scope."""
    _, worker, task = await _seed_task_with_status(
        sqlite_session,
        board_slug="gate-cancelled-rejected",
        status="cancelled",
    )
    with pytest.raises(HTTPException) as exc_info:
        await _attempt_post_event(
            sqlite_session,
            task=task,
            actor=worker,
            state="code_changed",
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pipeline_event_requires_in_progress"
    assert detail.get("current_status") == "cancelled"
