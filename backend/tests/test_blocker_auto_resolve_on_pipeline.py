# ruff: noqa: INP001
"""Phase V §I9 Fix 2 — system-authored pipeline Blockers must auto-resolve
when the corresponding pipeline events fill in.

Background: AC5 incident at 2026-05-02 01:39-01:48 UTC. Lead opened a
``pipeline_missing_review_gate`` Blocker because worker pipeline events
were missing. Worker posted the events, making ``pipeline.ready=true``.
But the Blocker entity was never explicitly resolved — it stayed open
for ~12 hours, dragging ``is_blocked=True`` along with it and hiding the
task from the lead's drain loop.

The fix: pipeline-shaped Blockers (machine-generated, with reason_code in
the system-authored set) auto-close when their unblock condition becomes
true. Manual blockers (operator-decision, content gates, etc.) stay
manual — they require explicit human resolution.

These tests pin the contract:
- AC5-shaped repro: ready=true after final event → Blocker auto-resolves
- Idempotency: events arriving for an already-ready task don't re-resolve
  or undo earlier resolutions
- Manual scope: non-pipeline reason_codes are NEVER auto-resolved
- Cross-task isolation: a pipeline event on task A doesn't touch task B
  Blockers
- Race window: Blocker created AFTER pipeline events landed must still
  auto-resolve (retroactive reconcile path on Blocker create)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.agents import Agent
from app.models.blockers import Blocker
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


async def _setup_board_with_in_progress_task(
    session: AsyncSession,
    *,
    board_slug: str,
    task_title: str,
    packet_commit_sha: str = "abcdef0",
) -> tuple[Board, Agent, Task]:
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
    in_progress_anchor = datetime(2026, 5, 2, 0, 30)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=task_title,
        status="in_progress",
        assigned_agent_id=worker_id,
        in_progress_at=in_progress_anchor,
        packet_commit_sha=packet_commit_sha,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, worker, task


async def _post_event(
    session: AsyncSession,
    *,
    task: Task,
    actor: Agent,
    state: str,
    commit_sha: str | None = None,
    artifact_hash: str | None = None,
    deploy_target: str | None = None,
    live_sha: str | None = None,
    evidence: dict | None = None,
) -> None:
    payload = TaskPipelineEventCreate(
        state=state,
        commit_sha=commit_sha,
        artifact_hash=artifact_hash,
        deploy_target=deploy_target,
        live_sha=live_sha,
        evidence=evidence,
    )
    await tasks_api.record_task_pipeline_event(
        payload=payload,
        task=task,
        session=session,
        actor=_ActorStub(agent=actor),
    )


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
    """Post the 6 events that make ``pipeline.ready=true``."""
    await _post_event(session, task=task, actor=actor, state="code_changed", commit_sha=commit_sha)
    await _post_event(session, task=task, actor=actor, state="committed", commit_sha=commit_sha)
    await _post_event(
        session, task=task, actor=actor, state="built",
        commit_sha=commit_sha, artifact_hash=artifact_hash,
    )
    await _post_event(
        session, task=task, actor=actor, state="deployed",
        artifact_hash=artifact_hash, deploy_target=deploy_target,
    )
    await _post_event(
        session, task=task, actor=actor, state="live_build_verified",
        deploy_target=deploy_target, live_sha=live_sha,
    )
    await _post_event(
        session, task=task, actor=actor, state="runtime_verified",
        deploy_target=deploy_target, evidence={"qa_browser_snapshot": "ok"},
    )


@pytest.mark.asyncio
async def test_pipeline_blocker_auto_resolves_when_pipeline_ready(
    sqlite_session: AsyncSession,
) -> None:
    """AC5 repro: open pipeline_missing_review_gate Blocker auto-resolves
    when worker fills in the missing pipeline events."""
    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="ac5-repro",
        task_title="AC5 — pipeline blocker auto-resolve",
    )
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)
    assert blocker.resolved_at is None

    await _post_full_pipeline(sqlite_session, task=task, actor=worker)

    await sqlite_session.refresh(blocker)
    assert blocker.resolved_at is not None, (
        "pipeline_missing_review_gate Blocker must auto-resolve when "
        "all required pipeline events are present"
    )


@pytest.mark.asyncio
async def test_pipeline_blocker_does_not_resolve_when_pipeline_partial(
    sqlite_session: AsyncSession,
) -> None:
    """Partial pipeline events do not flip pipeline.ready and must NOT
    auto-resolve the Blocker."""
    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="partial-events",
        task_title="Partial pipeline events",
    )
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)

    # Only post code_changed + committed — built/deployed/etc. missing.
    await _post_event(sqlite_session, task=task, actor=worker, state="code_changed", commit_sha="abc")
    await _post_event(sqlite_session, task=task, actor=worker, state="committed", commit_sha="abc")

    await sqlite_session.refresh(blocker)
    assert blocker.resolved_at is None, (
        "Blocker must stay open while pipeline.ready=false"
    )


@pytest.mark.asyncio
async def test_manual_blocker_is_never_auto_resolved(
    sqlite_session: AsyncSession,
) -> None:
    """Operator-policy / content-gate / approval-shaped Blockers must
    require explicit human resolution. Auto-resolve must only fire for
    machine-generated pipeline-shaped reason codes."""
    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="manual-blocker",
        task_title="Manual blocker stays manual",
    )
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="operator",
        owner_role="Operator",
        reason_code="operator_policy",
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)

    await _post_full_pipeline(sqlite_session, task=task, actor=worker)

    await sqlite_session.refresh(blocker)
    assert blocker.resolved_at is None, (
        "operator_policy Blocker must NOT be auto-resolved by pipeline "
        "events — manual blockers require explicit human resolution"
    )


@pytest.mark.asyncio
async def test_pipeline_event_does_not_resolve_other_task_blockers(
    sqlite_session: AsyncSession,
) -> None:
    """Pipeline events on task A must not touch Blockers on task B."""
    board, worker, task_a = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="cross-task",
        task_title="Task A",
    )
    task_b_id = uuid4()
    task_b = Task(
        id=task_b_id,
        board_id=board.id,
        title="Task B (unrelated)",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=datetime(2026, 5, 2, 0, 30),
        packet_commit_sha="zzz9999",
    )
    sqlite_session.add(task_b)
    blocker_b = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task_b_id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    sqlite_session.add(blocker_b)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker_b)

    await _post_full_pipeline(sqlite_session, task=task_a, actor=worker)

    await sqlite_session.refresh(blocker_b)
    assert blocker_b.resolved_at is None, (
        "Pipeline events on task A must not auto-resolve Blockers "
        "scoped to task B"
    )


@pytest.mark.asyncio
async def test_pipeline_blocker_does_not_resolve_using_old_cycle_events(
    sqlite_session: AsyncSession,
) -> None:
    """Codex Fix 2 review caught: ``list_task_pipeline_events`` with no
    ``since`` filter would let pipeline events from an OLD review cycle
    falsely satisfy ``pipeline.ready=true`` for a NEW cycle's Blocker.

    Repro: task completes a review cycle (events present), gets sent to
    rework, transitions back to in_progress (new cycle starts). Lead
    opens a new pipeline_missing_review_gate Blocker for the new cycle.
    Auto-resolve must scope event lookup to ``task.in_progress_at`` so
    old-cycle events don't satisfy the new-cycle Blocker.
    """
    from app.models.task_pipeline_events import TaskPipelineEvent

    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="cycle-scope",
        task_title="Cycle scope regression",
        packet_commit_sha="oldcycle",
    )
    # Old cycle: insert 6 events with old created_at, predating
    # in_progress_at by snapshotting an "earlier" cycle.
    old_cycle_anchor = datetime(2026, 4, 30, 12, 0)
    for state, fields in (
        ("code_changed", {"commit_sha": "old"}),
        ("committed", {"commit_sha": "old"}),
        ("built", {"commit_sha": "old", "artifact_hash": "olddead"}),
        ("deployed", {"artifact_hash": "olddead", "deploy_target": "http://old"}),
        ("live_build_verified", {"deploy_target": "http://old", "live_sha": "oldlive"}),
        ("runtime_verified", {"deploy_target": "http://old", "evidence": {"qa_browser_snapshot": "old"}}),
    ):
        sqlite_session.add(
            TaskPipelineEvent(
                board_id=board.id,
                task_id=task.id,
                agent_id=worker.id,
                state=state,
                source="api",
                created_at=old_cycle_anchor,
                **fields,
            ),
        )
    await sqlite_session.commit()
    # New cycle: task moved back to in_progress AFTER old events.
    new_cycle_anchor = datetime(2026, 5, 2, 14, 0)
    task.in_progress_at = new_cycle_anchor
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)
    # Lead opens a new-cycle Blocker. Old events predate new in_progress_at.
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)
    # Helper should NOT resolve — no NEW cycle events yet.
    from app.services.blockers import auto_resolve_pipeline_blockers_if_ready

    resolved = await auto_resolve_pipeline_blockers_if_ready(
        sqlite_session,
        board_id=board.id,
        task_id=task.id,
    )
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)
    assert resolved == 0, (
        f"Expected 0 resolutions (old cycle events shouldn't satisfy new cycle); "
        f"got {resolved}"
    )
    assert blocker.resolved_at is None, (
        "Old-cycle pipeline events must NOT auto-resolve a new-cycle Blocker"
    )


@pytest.mark.asyncio
async def test_pipeline_blocker_auto_resolves_on_overwrite_merge_path(
    sqlite_session: AsyncSession,
) -> None:
    """Codex Fix 2 review caught: ``record_task_pipeline_event`` has an
    overwrite-merge fast-path that returns BEFORE my auto-resolve hook.
    If the merge supplies the final missing required field (making
    pipeline.ready=true), the Blocker would stay open until some later
    pipeline event arrived. The merge path must also call the resolver.
    """
    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="merge-path",
        task_title="Merge-path resolver coverage",
    )
    # Post 5 of 6 events normally.
    await _post_event(sqlite_session, task=task, actor=worker, state="code_changed", commit_sha="abc")
    await _post_event(sqlite_session, task=task, actor=worker, state="committed", commit_sha="abc")
    # `built` event posted WITHOUT artifact_hash via overwrite path.
    # Actually, the API rejects missing required fields — so simulate
    # by inserting the partial event directly bypassing the validation.
    from app.models.task_pipeline_events import TaskPipelineEvent

    sqlite_session.add(
        TaskPipelineEvent(
            board_id=board.id,
            task_id=task.id,
            agent_id=worker.id,
            state="built",
            source="api",
            commit_sha="abc",
            artifact_hash=None,  # missing — pipeline.ready=false
        ),
    )
    await sqlite_session.commit()
    # Posts the rest normally.
    await _post_event(
        sqlite_session, task=task, actor=worker, state="deployed",
        artifact_hash="dead", deploy_target="http://target",
    )
    await _post_event(
        sqlite_session, task=task, actor=worker, state="live_build_verified",
        deploy_target="http://target", live_sha="live",
    )
    await _post_event(
        sqlite_session, task=task, actor=worker, state="runtime_verified",
        deploy_target="http://target", evidence={"ok": True},
    )
    # Now open the Blocker. Pipeline still NOT ready — built has no artifact_hash.
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    await sqlite_session.refresh(blocker)
    # Final event: overwrite-merge supplies the missing artifact_hash.
    payload = TaskPipelineEventCreate(
        state="built",
        commit_sha="abc",
        artifact_hash="dead",
        overwrite=True,
    )
    await tasks_api.record_task_pipeline_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=worker),
    )
    # Blocker should auto-resolve on the merge path.
    await sqlite_session.refresh(blocker)
    assert blocker.resolved_at is not None, (
        "Overwrite-merge that supplies a missing required field must "
        "trigger the auto-resolve hook same as a fresh insert path"
    )


@pytest.mark.asyncio
async def test_blocker_created_after_pipeline_ready_auto_resolves_retroactively(
    sqlite_session: AsyncSession,
) -> None:
    """Retroactive reconcile: race where pipeline events arrive BEFORE
    the Blocker is opened. The auto-resolve hook must also fire on
    Blocker create when the unblock condition is already true."""
    board, worker, task = await _setup_board_with_in_progress_task(
        sqlite_session,
        board_slug="retroactive",
        task_title="Race: events before Blocker",
    )
    # Post all events first — pipeline.ready=true before any Blocker.
    await _post_full_pipeline(sqlite_session, task=task, actor=worker)

    # Now create a system-authored pipeline Blocker via the API
    # path (which is the only path that goes through the reconcile
    # hook on Blocker create). Direct DB insert wouldn't trigger the
    # API hook — but in practice the lead's drain loop opens these
    # via the API, so testing the API path is the realistic case.
    from app.api.blockers import create_task_blocker
    from app.schemas.blockers import BlockerCreate

    payload = BlockerCreate(
        category="runtime",
        owner_role="Programmer-Frontend",
        reason_code="pipeline_missing_review_gate",
    )
    created = await create_task_blocker(
        payload=payload,
        board=board,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=worker),
    )

    # Reload via DB to bypass any in-memory staleness
    blocker = (
        await sqlite_session.exec(
            select(Blocker).where(col(Blocker.id) == created.id),
        )
    ).first()
    assert blocker is not None
    assert blocker.resolved_at is not None, (
        "Blocker created when pipeline.ready=true must auto-resolve "
        "retroactively — otherwise concurrent open-after-events race "
        "leaves the Blocker stuck"
    )
