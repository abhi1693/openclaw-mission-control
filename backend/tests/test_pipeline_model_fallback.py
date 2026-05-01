"""Tests for the ``model_fallback`` informational pipeline event.

Validates the OpenClaw 2026.4.27 ``model.fallback_step`` trajectory event
support: schema-level evidence-key validation, exclusion from readiness
gates, and surfacing of the latest fallback step on review-readiness
responses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.models.task_pipeline_events import TaskPipelineEvent
from app.schemas.task_pipeline_events import (
    INFORMATIONAL_PIPELINE_STATES,
    MODEL_FALLBACK_REQUIRED_EVIDENCE_KEYS,
    TaskPipelineEventCreate,
)
from app.services.task_pipeline import (
    FRONTEND_REVIEW_PIPELINE_STATES,
    latest_model_fallback_step,
    pipeline_missing_states,
    pipeline_present_states,
)


def _event(
    *,
    state: str,
    created_at: datetime | None = None,
    commit_sha: str | None = None,
    artifact_hash: str | None = None,
    deploy_target: str | None = None,
    live_sha: str | None = None,
    evidence: dict[str, object] | None = None,
) -> TaskPipelineEvent:
    return TaskPipelineEvent(
        id=uuid4(),
        board_id=uuid4(),
        task_id=uuid4(),
        agent_id=None,
        state=state,
        source="test",
        commit_sha=commit_sha,
        artifact_hash=artifact_hash,
        deploy_target=deploy_target,
        live_sha=live_sha,
        evidence=evidence,
        created_at=created_at or datetime.now(UTC),
    )


# --- Schema-level evidence-key validation ---


class TestModelFallbackEvidenceValidation:
    """``state="model_fallback"`` requires evidence with the trajectory keys."""

    def test_create_rejects_missing_evidence_dict(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TaskPipelineEventCreate(state="model_fallback", evidence=None)
        assert "evidence" in str(exc.value).lower()

    def test_create_rejects_empty_evidence_dict(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TaskPipelineEventCreate(state="model_fallback", evidence={})
        assert "evidence" in str(exc.value).lower()

    def test_create_rejects_evidence_missing_required_keys(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TaskPipelineEventCreate(
                state="model_fallback",
                evidence={"from_model": "ollama/qwen3.5:cloud"},
            )
        message = str(exc.value)
        assert "to_model" in message
        assert "reason" in message

    def test_create_accepts_evidence_with_all_required_keys(self) -> None:
        event = TaskPipelineEventCreate(
            state="model_fallback",
            evidence={
                "from_model": "ollama/qwen3.5:cloud",
                "to_model": "ollama/glm-5.1:cloud",
                "reason": "timeout",
            },
        )
        assert event.state == "model_fallback"
        assert event.evidence is not None
        assert MODEL_FALLBACK_REQUIRED_EVIDENCE_KEYS.issubset(event.evidence.keys())

    def test_create_accepts_evidence_with_extra_keys(self) -> None:
        """Extra trajectory metadata is preserved verbatim."""
        event = TaskPipelineEventCreate(
            state="model_fallback",
            evidence={
                "from_model": "ollama/qwen3.5:cloud",
                "to_model": "ollama/glm-5.1:cloud",
                "reason": "timeout",
                "chain_position": 1,
                "final_outcome": "succeeded",
                "request_id": "abc-123",
            },
        )
        assert event.evidence is not None
        assert event.evidence["chain_position"] == 1

    def test_non_fallback_state_unaffected_by_evidence_validator(self) -> None:
        """Other states still accept events with no evidence dict."""
        event = TaskPipelineEventCreate(state="committed", commit_sha="abc1234")
        assert event.state == "committed"
        assert event.evidence is None


# --- Readiness exclusion ---


class TestModelFallbackReadinessExclusion:
    """``model_fallback`` events must never affect ``ready`` gates."""

    def test_model_fallback_in_informational_set(self) -> None:
        assert "model_fallback" in INFORMATIONAL_PIPELINE_STATES

    def test_present_states_excludes_model_fallback(self) -> None:
        events = [
            _event(state="code_changed"),
            _event(
                state="model_fallback",
                evidence={
                    "from_model": "a",
                    "to_model": "b",
                    "reason": "timeout",
                },
            ),
            _event(state="committed", commit_sha="abc1234"),
        ]
        present = pipeline_present_states(events)
        assert "model_fallback" not in present
        assert "code_changed" in present
        assert "committed" in present

    def test_only_fallback_events_yield_empty_present(self) -> None:
        """A task with only a fallback step has no readiness progress."""
        events = [
            _event(
                state="model_fallback",
                evidence={
                    "from_model": "a",
                    "to_model": "b",
                    "reason": "timeout",
                },
            ),
        ]
        assert pipeline_present_states(events) == []

    def test_missing_states_unchanged_by_fallback_event(self) -> None:
        """Adding a fallback event does not satisfy any required state."""
        events_without = [_event(state="code_changed")]
        events_with_fallback = [
            *events_without,
            _event(
                state="model_fallback",
                evidence={
                    "from_model": "a",
                    "to_model": "b",
                    "reason": "timeout",
                },
            ),
        ]
        missing_without = pipeline_missing_states(events_without)
        missing_with = pipeline_missing_states(events_with_fallback)
        assert missing_without == missing_with
        # Sanity: the readiness frontier still requires the rest of the gates.
        assert "committed" in missing_with
        assert "model_fallback" not in FRONTEND_REVIEW_PIPELINE_STATES


# --- Latest fallback step retrieval ---


class TestLatestModelFallbackStep:
    """``latest_model_fallback_step`` returns the most recent fallback event."""

    def test_returns_none_when_no_fallback_events(self) -> None:
        events = [_event(state="code_changed"), _event(state="committed", commit_sha="x")]
        assert latest_model_fallback_step(events) is None

    def test_returns_only_fallback_when_one_exists(self) -> None:
        target = _event(
            state="model_fallback",
            evidence={
                "from_model": "ollama/qwen3.5:cloud",
                "to_model": "ollama/glm-5.1:cloud",
                "reason": "timeout",
            },
        )
        events = [
            _event(state="code_changed"),
            target,
            _event(state="committed", commit_sha="x"),
        ]
        result = latest_model_fallback_step(events)
        assert result is target

    def test_returns_most_recent_when_multiple_fallbacks(self) -> None:
        base = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
        oldest = _event(
            state="model_fallback",
            created_at=base,
            evidence={"from_model": "a", "to_model": "b", "reason": "timeout"},
        )
        middle = _event(
            state="model_fallback",
            created_at=base + timedelta(minutes=1),
            evidence={"from_model": "b", "to_model": "c", "reason": "overloaded"},
        )
        newest = _event(
            state="model_fallback",
            created_at=base + timedelta(minutes=2),
            evidence={"from_model": "c", "to_model": "d", "reason": "billing"},
        )
        events = [middle, newest, oldest]  # arbitrary insertion order
        result = latest_model_fallback_step(events)
        assert result is newest
        assert result is not None and result.evidence is not None
        assert result.evidence["reason"] == "billing"


# --- SQL-level fetch (Codex 4th-pass finding #7: avoid N+1) ---


class TestFetchLatestModelFallbackStepSql:
    """``fetch_latest_model_fallback_step`` pushes the filter to SQL."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_fallback_events_in_db(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import fetch_latest_model_fallback_step

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                result = await fetch_latest_model_fallback_step(
                    session, task_id=uuid4()
                )
                assert result is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_filters_to_state_model_fallback_at_sql_level(self) -> None:
        """Confirm ``state = 'model_fallback'`` is in the WHERE, not Python."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import fetch_latest_model_fallback_step

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                task_id = uuid4()
                base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
                # Seed a non-fallback and a fallback; filter must skip the
                # non-fallback row even though it's newer.
                committed = TaskPipelineEvent(
                    id=uuid4(),
                    board_id=uuid4(),
                    task_id=task_id,
                    agent_id=None,
                    state="committed",
                    source="test",
                    commit_sha="abc1234",
                    created_at=base + timedelta(minutes=5),
                )
                fallback_old = TaskPipelineEvent(
                    id=uuid4(),
                    board_id=uuid4(),
                    task_id=task_id,
                    agent_id=None,
                    state="model_fallback",
                    source="test",
                    evidence={
                        "from_model": "x",
                        "to_model": "y",
                        "reason": "timeout",
                    },
                    created_at=base,
                )
                fallback_newer = TaskPipelineEvent(
                    id=uuid4(),
                    board_id=uuid4(),
                    task_id=task_id,
                    agent_id=None,
                    state="model_fallback",
                    source="test",
                    evidence={
                        "from_model": "y",
                        "to_model": "z",
                        "reason": "billing",
                    },
                    created_at=base + timedelta(minutes=1),
                )
                session.add_all([committed, fallback_old, fallback_newer])
                await session.commit()

                result = await fetch_latest_model_fallback_step(
                    session, task_id=task_id
                )
                assert result is not None
                assert result.state == "model_fallback"
                assert result.id == fallback_newer.id
                assert result.evidence is not None
                assert result.evidence["reason"] == "billing"
        finally:
            await engine.dispose()


# --- Batched SQL fetch (lead-loop N+1 fix) ---


class TestFetchLatestModelFallbackStepsForTasks:
    """``fetch_latest_model_fallback_steps_for_tasks`` returns one SQL pass."""

    @pytest.mark.asyncio
    async def test_empty_task_ids_returns_empty_dict(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import (
            fetch_latest_model_fallback_steps_for_tasks,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                result = await fetch_latest_model_fallback_steps_for_tasks(
                    session, task_ids=[]
                )
                assert result == {}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_latest_per_task_skipping_other_states(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import (
            fetch_latest_model_fallback_steps_for_tasks,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                board_id = uuid4()
                task_a = uuid4()
                task_b = uuid4()
                task_c = uuid4()  # has no fallback events
                base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

                def _ev(
                    task_id: UUID,
                    state: str,
                    minute: int,
                    reason: str | None = None,
                ) -> TaskPipelineEvent:
                    evidence = (
                        {"from_model": "x", "to_model": "y", "reason": reason}
                        if reason
                        else None
                    )
                    return TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task_id,
                        agent_id=None,
                        state=state,
                        source="test",
                        evidence=evidence,
                        created_at=base + timedelta(minutes=minute),
                    )

                rows = [
                    _ev(task_a, "model_fallback", 0, "timeout"),
                    _ev(task_a, "model_fallback", 5, "billing"),  # latest for A
                    _ev(task_a, "committed", 10),  # newer but not fallback
                    _ev(task_b, "model_fallback", 1, "overloaded"),  # only fallback for B
                    _ev(task_c, "code_changed", 7),  # no fallback for C
                ]
                rows[2].commit_sha = "abc1234"  # type: ignore[attr-defined]
                session.add_all(rows)
                await session.commit()

                result = await fetch_latest_model_fallback_steps_for_tasks(
                    session, task_ids=[task_a, task_b, task_c]
                )

                assert set(result.keys()) == {task_a, task_b}  # task_c absent
                evidence_a = result[task_a].evidence
                evidence_b = result[task_b].evidence
                assert evidence_a is not None
                assert evidence_a["reason"] == "billing"
                assert evidence_b is not None
                assert evidence_b["reason"] == "overloaded"
        finally:
            await engine.dispose()


# --- Batched all-events fetch (lead pipeline-missing N+1 fix) ---


class TestListTaskPipelineEventsForTasks:
    """``list_task_pipeline_events_for_tasks`` returns one SQL pass and
    groups events by task_id, sorted ``created_at DESC`` per group.
    """

    @pytest.mark.asyncio
    async def test_empty_task_ids_returns_empty_dict(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import list_task_pipeline_events_for_tasks

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                result = await list_task_pipeline_events_for_tasks(session, task_ids=[])
                assert result == {}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_groups_events_by_task_with_one_query(self) -> None:
        from sqlalchemy import event as sa_event
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        from app.services.task_pipeline import list_task_pipeline_events_for_tasks

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn, conn.begin():
            await conn.run_sync(SQLModel.metadata.create_all)

        query_count = 0

        @sa_event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _count(*_args: object, **_kwargs: object) -> None:
            nonlocal query_count
            query_count += 1

        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                board_id = uuid4()
                task_a = uuid4()
                task_b = uuid4()
                task_c = uuid4()  # has no events at all
                base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

                rows = [
                    TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task_a,
                        agent_id=None,
                        state="committed",
                        source="test",
                        commit_sha="abc1234",
                        created_at=base,
                    ),
                    TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task_a,
                        agent_id=None,
                        state="built",
                        source="test",
                        commit_sha="abc1234",
                        artifact_hash="art-1",
                        created_at=base + timedelta(minutes=1),
                    ),
                    TaskPipelineEvent(
                        id=uuid4(),
                        board_id=board_id,
                        task_id=task_b,
                        agent_id=None,
                        state="code_changed",
                        source="test",
                        created_at=base,
                    ),
                ]
                session.add_all(rows)
                await session.commit()

                query_count = 0
                result = await list_task_pipeline_events_for_tasks(
                    session, task_ids=[task_a, task_b, task_c]
                )

                assert set(result.keys()) == {task_a, task_b}  # task_c absent
                assert len(result[task_a]) == 2
                # DESC order — newest first
                assert result[task_a][0].state == "built"
                assert result[task_a][1].state == "committed"
                assert len(result[task_b]) == 1
                assert query_count == 1, (
                    f"expected 1 query for batch fetch; got {query_count}"
                )
        finally:
            await engine.dispose()
