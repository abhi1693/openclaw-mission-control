# ruff: noqa: INP001

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api.deps import ActorContext
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.tasks import Task
from app.schemas.tasks import TaskUpdate


OLD_COMMIT_SHA = "a" * 40
NEW_COMMIT_SHA = "b" * 40


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_worker_task(
    session: AsyncSession,
    *,
    status: str = "in_progress",
    review_packet_type: str = "frontend_ui",
) -> tuple[Board, Agent, Task]:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    worker_id = uuid4()
    lead_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name="org"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        name="board",
        slug="board",
        gateway_id=gateway_id,
        comment_required_for_review=True,
    )
    session.add(board)
    worker = Agent(
        id=worker_id,
        name="Programmer-Frontend",
        board_id=board_id,
        gateway_id=gateway_id,
        status="online",
        identity_profile={"dev_acp_flow": "claude_then_codex_review"},
    )
    session.add(worker)
    session.add(
        Agent(
            id=lead_id,
            name="Supervisor",
            board_id=board_id,
            gateway_id=gateway_id,
            status="online",
            is_board_lead=True,
        ),
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Frontend task",
        description="",
        status=status,
        assigned_agent_id=worker_id,
        in_progress_at=utcnow(),
        review_packet_type=review_packet_type,
        validation_target="https://example.test",
        validation_target_kind="live_url",
        validation_target_scope="review",
    )
    session.add(task)
    await session.commit()
    return board, worker, task


async def _reload_task(session: AsyncSession, task_id: UUID) -> Task:
    task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
    assert task is not None
    return task


async def _record_frontend_pipeline_ready(
    session: AsyncSession,
    *,
    board: Board,
    worker: Agent,
    task: Task,
) -> None:
    for state in (
        "code_changed",
        "committed",
        "built",
        "deployed",
        "live_build_verified",
        "runtime_verified",
    ):
        session.add(
            TaskPipelineEvent(
                task_id=task.id,
                board_id=board.id,
                agent_id=worker.id,
                state=state,
                source="test",
                commit_sha="abc1234",
                artifact_hash="index-test.js",
                deploy_target="https://example.test",
                live_sha="abc1234",
                evidence={"summary": f"{state} evidence"},
            ),
        )
    await session.commit()


@pytest.mark.asyncio
async def test_worker_review_transition_rejects_source_level_completion_comment() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(session)

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Build passes and source grep found the keys.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "task_pipeline_incomplete"
            assert exc.value.detail["first_missing_state"] == "code_changed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_frontend_review_transition_accepts_structured_pipeline_events() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, worker, task = await _seed_worker_task(session)
            await _record_frontend_pipeline_ready(
                session,
                board=board,
                worker=worker,
                task=task,
            )

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="review",
                    comment="Implementation complete; structured pipeline evidence is recorded.",
                ),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "review"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_frontend_review_transition_rejects_structured_pipeline_stuck_at_commit_state() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, worker, task = await _seed_worker_task(session)
            for state in ("code_changed", "committed"):
                session.add(
                    TaskPipelineEvent(
                        task_id=task.id,
                        board_id=board.id,
                        agent_id=worker.id,
                        state=state,
                        source="test",
                        commit_sha="abc1234",
                    ),
                )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Implementation complete; awaiting backend gate.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "task_pipeline_incomplete"
            assert exc.value.detail["first_missing_state"] == "built"
            assert exc.value.detail["missing_states"] == [
                "built",
                "deployed",
                "live_build_verified",
                "runtime_verified",
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_requires_active_blocker_cleared_packet() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(session)
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        packet_commit_sha="abc1234",
                        comment=(
                            "FINAL_EVIDENCE_PACKET\n"
                            "Target: https://example.test\n"
                            "Build: index-test.js\n"
                        ),
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "task_active_blocker_clearance_required"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_accepts_active_blocker_cleared_packet() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, worker, task = await _seed_worker_task(session)
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()
            await _record_frontend_pipeline_ready(
                session,
                board=board,
                worker=worker,
                task=task,
            )

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="review",
                    packet_commit_sha="abc1234",
                    comment="Active blocker cleared: structured runtime evidence recorded",
                ),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "review"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_rejects_missing_packet_commit_sha() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "rework_no_commit"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_rejects_same_packet_commit_sha() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        packet_commit_sha=OLD_COMMIT_SHA,
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "rework_same_commit"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_accepts_new_packet_commit_sha() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="review",
                    packet_commit_sha=NEW_COMMIT_SHA,
                    comment="Active blocker cleared: fixed the reviewer blocker.",
                ),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "review"
            assert updated.packet_commit_sha == NEW_COMMIT_SHA
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_rejects_missing_packet_commit_sha_with_null_snapshot() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_entry_commit_sha = None
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "rework_no_commit"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_uses_durable_rework_marker_without_activity_event() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_started_at = utcnow()
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "rework_no_commit"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_pickup_preserves_durable_rework_marker() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            started_at = utcnow()
            task.status = "rework"
            task.in_progress_at = None
            task.rework_started_at = started_at
            await session.commit()

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="in_progress"),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "in_progress"
            reloaded = await _reload_task(session, task.id)
            assert reloaded.rework_started_at == started_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_rework_activity_does_not_override_newer_reroute_status() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            now = utcnow()
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                    created_at=now,
                ),
            )
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to inbox: Frontend task.",
                    created_at=now + timedelta(seconds=1),
                ),
            )
            await session.commit()

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="review",
                    comment="Ready for review after reroute.",
                ),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "review"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_marker_clears_after_successful_review_resubmission() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_started_at = utcnow()
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            await session.commit()

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="review",
                    packet_commit_sha=NEW_COMMIT_SHA,
                    comment="Active blocker cleared: fixed the reviewer blocker.",
                ),
                task=await _reload_task(session, task.id),
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "review"
            reloaded = await _reload_task(session, task.id)
            assert reloaded.rework_started_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rework_review_transition_rejects_invalid_packet_commit_sha() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="content_copy",
            )
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            task.packet_commit_sha = "newsha"
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Frontend task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "rework_invalid_commit_sha"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_implementation_rework_on_review_only_task_is_rejected() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, worker, task = await _seed_worker_task(
                session,
                review_packet_type="review_only",
            )
            task.rework_entry_commit_sha = OLD_COMMIT_SHA
            session.add(
                ActivityEvent(
                    event_type="task.status_changed",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                    message="Task moved to rework: Review task.",
                ),
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        status="review",
                        packet_commit_sha=NEW_COMMIT_SHA,
                        comment="Active blocker cleared: fixed the reviewer blocker.",
                    ),
                    task=await _reload_task(session, task.id),
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=worker),
                )

            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "review_only_rework_requires_packet_type_change"
    finally:
        await engine.dispose()
