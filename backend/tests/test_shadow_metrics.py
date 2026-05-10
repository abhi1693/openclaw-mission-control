# ruff: noqa: INP001
"""Unit tests for the Phase 0 shadow-metric emitter.

Covers amendment section A.2 (classifier wired into the comment write
path) and A.4 (append-only events, 90-day retention is a downstream
job — not tested here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.shadow_metric_events import ShadowMetricEvent
from app.services.shadow_metrics import (
    EVENT_COMMENT_ACK_ONLY,
    EVENT_COMMENT_NEAR_DUPLICATE,
    EVENT_TASK_ACTIONABILITY_VIOLATION,
    build_shadow_events_for_comment,
    emit_actionability_violation_metric,
)


@dataclass
class _FakeExecResult:
    rows: list[Any] = field(default_factory=list)

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None


@dataclass
class _FakeSession:
    """Minimal AsyncSession stand-in used for the prior-comment fetch."""

    prior: ActivityEvent | None = None

    async def exec(self, _statement: Any) -> _FakeExecResult:
        return _FakeExecResult(rows=[self.prior] if self.prior else [])


@pytest.mark.asyncio
async def test_clean_comment_emits_no_events() -> None:
    """Substantive, non-ack comment yields zero shadow events."""

    session = _FakeSession()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message="Filed PR #1 against master, tests passing. Running lighthouse now.",
        packet_type="frontend_ui",
    )
    assert result.shadow_events == []
    assert result.flags == []


@pytest.mark.asyncio
async def test_ack_only_comment_emits_paired_candidate_events() -> None:
    """An ack-theater comment emits the paired
    ack_only_candidate + echo_shape_candidate events. Phase VII
    ECHO_SHAPE is a strict-superset of ACK_ONLY on shape — keeping
    both gives operators separate signals to tune ``comment_policy_v1``
    dashboards vs ``comment_echo_guard_v1`` enforcement rollout."""

    session = _FakeSession()
    source_id = uuid4()
    task_id = uuid4()
    agent_id = uuid4()
    board_id = uuid4()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=task_id,
        board_id=board_id,
        agent_id=agent_id,
        source_event_id=source_id,
        message="Acknowledged. Holding exactly there. No status change. @lead",
        packet_type="frontend_ui",
    )
    event_types = {e.event_type for e in result.shadow_events}
    assert event_types == {
        EVENT_COMMENT_ACK_ONLY,
        "comment.echo_shape_candidate",
    }
    assert len(result.flags) == 2
    ack_event = next(e for e in result.shadow_events if e.event_type == EVENT_COMMENT_ACK_ONLY)
    assert isinstance(ack_event, ShadowMetricEvent)
    assert ack_event.task_id == task_id
    assert ack_event.agent_id == agent_id
    assert ack_event.board_id == board_id
    assert ack_event.source_event_id == source_id
    assert ack_event.classifier_metadata is not None
    assert ack_event.classifier_metadata["packet_type"] == "frontend_ui"


@pytest.mark.asyncio
async def test_near_duplicate_emits_event_when_prior_exists() -> None:
    """With a recent same-author prior, duplicate detection fires."""

    now = utcnow()
    prior_msg = "Acknowledged. Holding there."
    prior = ActivityEvent(
        event_type="task.comment",
        message=prior_msg,
        task_id=uuid4(),
        agent_id=uuid4(),
        created_at=now - timedelta(seconds=60),
    )
    session = _FakeSession(prior=prior)
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=prior.task_id or uuid4(),
        board_id=None,
        agent_id=prior.agent_id,
        source_event_id=uuid4(),
        message=prior_msg,  # identical -> jaccard 1.0
        packet_type="frontend_ui",
        now=now,
    )
    event_types = {e.event_type for e in result.shadow_events}
    assert EVENT_COMMENT_ACK_ONLY in event_types
    assert EVENT_COMMENT_NEAR_DUPLICATE in event_types


@pytest.mark.asyncio
async def test_user_comments_skip_classifier_entirely() -> None:
    """User comments (agent_id=None) are exempt from classification.

    The classifier measures agent noise; treating operator acks as
    data points pollutes the histogram.
    """

    session = _FakeSession(prior=None)
    # Ack-shaped message that would flag if an agent posted it:
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=None,
        source_event_id=uuid4(),
        message="Acknowledged. Holding exactly there. No status change.",
        packet_type="frontend_ui",
    )
    assert result.shadow_events == []
    assert result.flags == []


@pytest.mark.asyncio
async def test_prior_outside_window_does_not_trigger_duplicate() -> None:
    """A prior from 6 min ago is outside the 5-min dedup window."""

    now = utcnow()
    prior_msg = "Acknowledged. Holding there."
    prior = ActivityEvent(
        event_type="task.comment",
        message=prior_msg,
        task_id=uuid4(),
        agent_id=uuid4(),
        created_at=now - timedelta(minutes=6),
    )
    session = _FakeSession(prior=prior)
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=prior.task_id or uuid4(),
        board_id=None,
        agent_id=prior.agent_id,
        source_event_id=uuid4(),
        message=prior_msg,
        packet_type="frontend_ui",
        now=now,
    )
    # Ack-only still fires; near-duplicate does not because the prior
    # is outside the window. The _fake_session returns it anyway, but
    # the classifier's own gap check rejects it.
    event_types = {e.event_type for e in result.shadow_events}
    assert EVENT_COMMENT_ACK_ONLY in event_types
    assert EVENT_COMMENT_NEAR_DUPLICATE not in event_types


@pytest.mark.asyncio
async def test_db_failure_propagates_not_swallowed() -> None:
    """A broken session must raise — silent fallback hides incident signal.

    The caller's commit would fail on the same broken session anyway,
    so swallowing here only loses observability at the worst time.
    """

    class _ExplodingSession:
        async def exec(self, _statement: Any) -> _FakeExecResult:
            raise RuntimeError("simulated DB failure")

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await build_shadow_events_for_comment(
            _ExplodingSession(),  # type: ignore[arg-type]
            task_id=uuid4(),
            board_id=uuid4(),
            agent_id=uuid4(),
            source_event_id=uuid4(),
            message="Acknowledged. Holding there.",
            packet_type="frontend_ui",
        )


@pytest.mark.asyncio
async def test_classifier_exception_returns_empty_and_logs() -> None:
    """A bug inside classify() must not break the caller's commit."""

    import app.services.shadow_metrics as sm

    def _explode(*_a: Any, **_kw: Any) -> list[Any]:
        raise ValueError("simulated classifier bug")

    original = sm.classify
    sm.classify = _explode  # type: ignore[assignment]
    try:
        session = _FakeSession()
        result = await build_shadow_events_for_comment(
            session,  # type: ignore[arg-type]
            task_id=uuid4(),
            board_id=uuid4(),
            agent_id=uuid4(),
            source_event_id=uuid4(),
            message="Filed PR, tests passing.",
            packet_type="frontend_ui",
        )
        assert result.shadow_events == []
        assert result.flags == []
    finally:
        sm.classify = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_actionability_violation_emits_with_separate_session() -> None:
    """The actionability emitter uses its own short-lived session so the
    row survives when the caller's transaction rolls back after the raise.

    The test monkeypatches ``async_session_maker`` to capture the
    ShadowMetricEvent that would be persisted.
    """

    import app.services.shadow_metrics as sm

    captured: list[ShadowMetricEvent] = []
    commits: list[int] = [0]

    class _CaptureSession:
        async def __aenter__(self) -> "_CaptureSession":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        def add(self, value: Any) -> None:
            if isinstance(value, ShadowMetricEvent):
                captured.append(value)

        async def commit(self) -> None:
            commits[0] += 1

    def _maker() -> _CaptureSession:
        return _CaptureSession()

    original = sm.async_session_maker
    sm.async_session_maker = _maker  # type: ignore[assignment]
    try:
        task_id = uuid4()
        board_id = uuid4()
        agent_id = uuid4()
        await emit_actionability_violation_metric(
            task_id=task_id,
            board_id=board_id,
            agent_id=agent_id,
            status_value="in_progress",
            missing_fields=["validation_target", "review_packet_type"],
        )
    finally:
        sm.async_session_maker = original  # type: ignore[assignment]

    assert len(captured) == 1
    assert commits[0] == 1
    event = captured[0]
    assert event.event_type == EVENT_TASK_ACTIONABILITY_VIOLATION
    assert event.task_id == task_id
    assert event.board_id == board_id
    assert event.agent_id == agent_id
    assert event.classifier_metadata is not None
    assert event.classifier_metadata["status_value"] == "in_progress"
    assert event.classifier_metadata["missing_fields"] == [
        "validation_target",
        "review_packet_type",
    ]


@pytest.mark.asyncio
async def test_actionability_violation_emitter_swallows_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken session must not propagate out of the emitter, and the
    failure must be logged so operators can diagnose it.

    The 422 the caller is about to raise must not be delayed by an
    observability-only failure.
    """

    import app.services.shadow_metrics as sm

    class _ExplodingAddSession:
        async def __aenter__(self) -> "_ExplodingAddSession":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        def add(self, _value: Any) -> None:
            raise RuntimeError("simulated DB failure")

        async def commit(self) -> None:
            return None

    original = sm.async_session_maker
    sm.async_session_maker = lambda: _ExplodingAddSession()  # type: ignore[assignment]
    try:
        with caplog.at_level("ERROR", logger="app.services.shadow_metrics"):
            await emit_actionability_violation_metric(
                task_id=uuid4(),
                board_id=uuid4(),
                agent_id=None,
                status_value="review",
                missing_fields=["review_packet_type"],
            )
        assert "actionability_emit_failed" in caplog.text
    finally:
        sm.async_session_maker = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_oversized_message_skips_classifier() -> None:
    """Pathological message bodies don't stall the regex engine."""

    import app.services.shadow_metrics as sm

    session = _FakeSession()
    huge = "x" * (sm.MESSAGE_CLASSIFY_MAX_CHARS + 1)
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message=huge,
        packet_type="frontend_ui",
    )
    assert result.shadow_events == []
    assert result.flags == []


@pytest.mark.asyncio
async def test_classifier_result_exposes_flags_for_activity_event_stamp() -> None:
    """Phase I: callers need the flag list to stamp ActivityEvent.
    classifier_flags for fast GET /comments filtering."""

    from app.services.comment_classifier import ClassifierFlag

    session = _FakeSession()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message="Acknowledged. Holding exactly there. No status change. @lead",
        packet_type="frontend_ui",
    )
    assert ClassifierFlag.ACK_ONLY in result.flags
    assert result.classifier_ran is True
    # The stamping contract: flags list length == shadow events list length.
    # Each classifier flag becomes one shadow event AND one entry in the
    # denormalized classifier_flags column on the comment row.
    assert len(result.flags) == len(result.shadow_events)


@pytest.mark.asyncio
async def test_classifier_ran_false_for_user_comment() -> None:
    """agent_id=None paths return classifier_ran=False — the caller
    must leave ActivityEvent.classifier_flags as NULL."""

    session = _FakeSession()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=None,
        source_event_id=uuid4(),
        message="Acknowledged. Holding there.",
        packet_type="frontend_ui",
    )
    assert result.classifier_ran is False
    assert result.flags == []
    assert result.shadow_events == []


@pytest.mark.asyncio
async def test_classifier_ran_false_for_oversized_message() -> None:
    """Oversized bodies bypass classify() — classifier_ran must be False."""

    import app.services.shadow_metrics as sm

    session = _FakeSession()
    huge = "x" * (sm.MESSAGE_CLASSIFY_MAX_CHARS + 1)
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message=huge,
        packet_type="frontend_ui",
    )
    assert result.classifier_ran is False


@pytest.mark.asyncio
async def test_classifier_ran_true_for_clean_comment() -> None:
    """A substantive non-ack comment should run the classifier and
    produce classifier_ran=True with empty flags — the caller stamps
    ``[]`` on the DB column as 'observable clean'."""

    session = _FakeSession()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message="Filed PR #247 against master, tests passing.",
        packet_type="frontend_ui",
    )
    assert result.classifier_ran is True
    assert result.flags == []
    assert result.shadow_events == []


@pytest.mark.asyncio
async def test_lax_packet_type_suppresses_ack_only() -> None:
    """A short ack on a review_only task is legit, not theater."""

    session = _FakeSession()
    result = await build_shadow_events_for_comment(
        session,  # type: ignore[arg-type]
        task_id=uuid4(),
        board_id=uuid4(),
        agent_id=uuid4(),
        source_event_id=uuid4(),
        message="Acknowledged. Reassigning to Architect.",
        packet_type="review_only",
    )
    assert result.shadow_events == []
    assert result.flags == []
