# ruff: noqa: INP001
"""Regression tests for structured review verdict readiness."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.time import utcnow
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.task_review_events import TaskReviewEvent
from app.models.tasks import Task
from app.services.task_review_events import build_review_readiness


def _task(*, review_packet_type: str = "frontend_ui") -> Task:
    return Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Task under review",
        status="review",
        review_packet_type=review_packet_type,
        in_progress_at=utcnow(),
    )


def _event(
    task: Task,
    *,
    reviewer_role: str,
    verdict: str,
    minutes_after_cycle: int = 1,
    evidence: dict[str, object] | None = None,
) -> TaskReviewEvent:
    assert task.board_id is not None
    assert task.in_progress_at is not None
    return TaskReviewEvent(
        board_id=task.board_id,
        task_id=task.id,
        agent_id=uuid4(),
        reviewer_role=reviewer_role,
        verdict=verdict,
        evidence_type="browser" if reviewer_role == "qa_e2e" else "review",
        evidence=evidence,
        created_at=task.in_progress_at + timedelta(minutes=minutes_after_cycle),
    )


def test_frontend_review_readiness_requires_architect_and_qa_e2e_pass() -> None:
    task = _task(review_packet_type="frontend_ui")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(task, reviewer_role="qa_e2e", verdict="pass"),
        ],
    )

    assert readiness.ready is True
    assert readiness.required_roles == ["architect", "qa_e2e"]
    assert readiness.missing_roles == []
    assert readiness.blocking_roles == []


def test_latest_fail_blocks_even_when_required_roles_exist() -> None:
    task = _task(review_packet_type="backend_api")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(task, reviewer_role="qa_unit", verdict="pass"),
            _event(task, reviewer_role="qa_unit", verdict="fail", minutes_after_cycle=2),
        ],
    )

    assert readiness.ready is False
    assert readiness.missing_roles == []
    assert readiness.blocking_roles == ["qa_unit"]


def test_stale_verdict_before_current_cycle_does_not_count() -> None:
    task = _task(review_packet_type="infra_ops")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="devops", verdict="pass", minutes_after_cycle=-1),
        ],
    )

    assert readiness.ready is False
    assert readiness.required_roles == ["devops"]
    assert readiness.missing_roles == ["devops"]


def test_review_only_architect_pass_requires_child_task_evidence() -> None:
    task = _task(review_packet_type="review_only")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == [
        "review_only_architect_pass_missing_child_task_evidence"
    ]


def test_review_only_architect_pass_accepts_declared_child_task_ids() -> None:
    task = _task(review_packet_type="review_only")
    child_task_id = uuid4()
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"planned_child_task_ids": [str(child_task_id)]},
            ),
        ],
        board_task_ids={task.id, child_task_id},
    )

    assert readiness.ready is True
    assert readiness.declared_child_task_ids == [child_task_id]
    assert readiness.artifact_issues == []


def test_review_only_architect_pass_blocks_missing_declared_child_task_ids() -> None:
    task = _task(review_packet_type="review_only")
    child_task_id = uuid4()
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"planned_child_task_ids": [str(child_task_id)]},
            ),
        ],
        board_task_ids={task.id},
    )

    assert readiness.ready is False
    assert readiness.declared_child_task_ids == [child_task_id]
    assert readiness.missing_child_task_ids == [child_task_id]
    assert readiness.artifact_issues == [
        "review_only_architect_pass_child_tasks_not_found"
    ]


def test_review_only_architect_pass_accepts_explicit_no_child_tasks_required() -> None:
    task = _task(review_packet_type="review_only")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"no_child_tasks_required": True},
            ),
        ],
    )

    assert readiness.ready is True
    assert readiness.artifact_issues == []


# --- B2: latest_fallback_step surfacing on review readiness ---


def _fallback_event(task: Task, *, minutes_after_cycle: int = 2) -> TaskPipelineEvent:
    """Build a model_fallback pipeline event for readiness tests."""
    assert task.board_id is not None
    assert task.in_progress_at is not None
    return TaskPipelineEvent(
        id=uuid4(),
        board_id=task.board_id,
        task_id=task.id,
        agent_id=None,
        state="model_fallback",
        source="test",
        evidence={
            "from_model": "ollama/qwen3.5:cloud",
            "to_model": "ollama/glm-5.1:cloud",
            "reason": "timeout",
            "chain_position": 1,
            "final_outcome": "next_fallback",
        },
        created_at=task.in_progress_at + timedelta(minutes=minutes_after_cycle),
    )


class TestLatestFallbackStepSurfacing:
    """Codex re-pass goal-aligned: B2 surfaces fallback context inline."""

    def test_review_readiness_omits_fallback_when_none_occurred(self) -> None:
        task = _task(review_packet_type="frontend_ui")
        readiness = build_review_readiness(
            task=task,
            events=[
                _event(task, reviewer_role="architect", verdict="pass"),
                _event(task, reviewer_role="qa_e2e", verdict="pass"),
            ],
        )
        assert readiness.latest_fallback_step is None

    def test_review_readiness_includes_fallback_when_present(self) -> None:
        task = _task(review_packet_type="frontend_ui")
        fallback = _fallback_event(task)
        readiness = build_review_readiness(
            task=task,
            events=[
                _event(task, reviewer_role="architect", verdict="pass"),
                _event(task, reviewer_role="qa_e2e", verdict="pass"),
            ],
            latest_fallback_step=fallback,
        )
        assert readiness.latest_fallback_step is not None
        assert readiness.latest_fallback_step.state == "model_fallback"
        assert readiness.latest_fallback_step.evidence is not None
        assert readiness.latest_fallback_step.evidence["from_model"] == "ollama/qwen3.5:cloud"
        assert readiness.latest_fallback_step.evidence["to_model"] == "ollama/glm-5.1:cloud"

    def test_fallback_does_not_affect_ready_calculation(self) -> None:
        """Fallback events are informational only; they must not gate ready=True."""
        task = _task(review_packet_type="frontend_ui")
        fallback = _fallback_event(task)
        readiness = build_review_readiness(
            task=task,
            events=[
                _event(task, reviewer_role="architect", verdict="pass"),
                _event(task, reviewer_role="qa_e2e", verdict="pass"),
            ],
            latest_fallback_step=fallback,
        )
        # ready stays True even with a fallback present
        assert readiness.ready is True

    def test_fallback_serializes_via_pipeline_event_read(self) -> None:
        """The surfaced fallback uses the canonical TaskPipelineEventRead shape."""
        task = _task(review_packet_type="frontend_ui")
        fallback = _fallback_event(task)
        readiness = build_review_readiness(
            task=task,
            events=[
                _event(task, reviewer_role="architect", verdict="pass"),
                _event(task, reviewer_role="qa_e2e", verdict="pass"),
            ],
            latest_fallback_step=fallback,
        )
        # The fallback should round-trip through the model schema
        assert readiness.latest_fallback_step is not None
        assert readiness.latest_fallback_step.task_id == task.id
        assert readiness.latest_fallback_step.created_at == fallback.created_at


# --- Lead-loop batch readiness (N+1 fix) ---


class TestGetTaskReviewReadinessBatch:
    """``get_task_review_readiness_batch`` issues a constant query count
    regardless of N tasks (board_task_ids per board + 2 batch fetches).
    """

    @pytest.mark.asyncio
    async def test_empty_tasks_returns_empty_dict(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_review_events import get_task_review_readiness_batch

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                result = await get_task_review_readiness_batch(session, tasks=[])
                assert result == {}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_query_count_independent_of_task_count(self) -> None:
        """4 review tasks on the same board should produce a constant query
        count (1 board_task_ids + 1 review-events + 1 fallbacks = 3),
        not 3 per task = 12.
        """
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_review_events import get_task_review_readiness_batch

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)

        query_count = 0

        from sqlalchemy import event as sa_event

        @sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _count(*_args: object, **_kwargs: object) -> None:
            nonlocal query_count
            query_count += 1

        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                board_id = uuid4()
                tasks = [
                    Task(
                        id=uuid4(),
                        board_id=board_id,
                        title=f"task-{idx}",
                        status="review",
                        review_packet_type="frontend_ui",
                        in_progress_at=utcnow(),
                    )
                    for idx in range(4)
                ]
                session.add_all(tasks)
                for task in tasks:
                    session.add(_event(task, reviewer_role="architect", verdict="pass"))
                    session.add(_event(task, reviewer_role="qa_e2e", verdict="pass"))
                await session.commit()

                query_count = 0
                result = await get_task_review_readiness_batch(session, tasks=tasks)

                assert len(result) == 4
                assert all(readiness.ready is True for readiness in result.values())
                # 1 board_task_ids query + 1 review-events batch + 1 fallback batch.
                # Total constant regardless of N tasks.
                assert query_count == 3, f"expected 3 queries, got {query_count}"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_per_task_cycle_since_filter_applied_in_batch(self) -> None:
        """Pre-cycle review events must be excluded per task even when
        the batch fetch pulls them all in one query.
        """
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_review_events import get_task_review_readiness_batch

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                board_id = uuid4()
                cycle_start = utcnow()
                task = Task(
                    id=uuid4(),
                    board_id=board_id,
                    title="task with old verdicts",
                    status="review",
                    review_packet_type="frontend_ui",
                    in_progress_at=cycle_start,
                )
                # Pre-cycle events (must be excluded from readiness calc)
                pre_cycle_architect = TaskReviewEvent(
                    board_id=board_id,
                    task_id=task.id,
                    agent_id=uuid4(),
                    reviewer_role="architect",
                    verdict="fail",
                    evidence_type="review",
                    created_at=cycle_start - timedelta(hours=1),
                )
                # Current-cycle events (counted)
                current_architect = TaskReviewEvent(
                    board_id=board_id,
                    task_id=task.id,
                    agent_id=uuid4(),
                    reviewer_role="architect",
                    verdict="pass",
                    evidence_type="review",
                    created_at=cycle_start + timedelta(minutes=1),
                )
                current_qa = TaskReviewEvent(
                    board_id=board_id,
                    task_id=task.id,
                    agent_id=uuid4(),
                    reviewer_role="qa_e2e",
                    verdict="pass",
                    evidence_type="browser",
                    created_at=cycle_start + timedelta(minutes=2),
                )
                session.add_all([task, pre_cycle_architect, current_architect, current_qa])
                await session.commit()

                result = await get_task_review_readiness_batch(session, tasks=[task])

                readiness = result[task.id]
                assert readiness.ready is True
                # Serialized events must only include current-cycle
                assert len(readiness.events) == 2
                assert all(e.created_at >= cycle_start for e in readiness.events)
        finally:
            await engine.dispose()
