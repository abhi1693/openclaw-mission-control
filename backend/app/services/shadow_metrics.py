"""Phase 0 shadow-metric emitters.

This module wires the shared comment classifier into the comment write
path without changing caller-visible behavior. Each hook returns a list
of ``ShadowMetricEvent`` rows the caller adds to the same session so
the comment and its observability signals commit atomically.

See ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
sections A.2 and A.4.

Retention of the events themselves is controlled by
``settings.shadow_metric_retention_days`` (default 90) per amendment
§A.4. The purge job itself is **not yet implemented** — operators
should treat the table as append-only until a nightly job is wired
(expected in a follow-up commit). Until then the created_at index
keeps a manual ``DELETE FROM shadow_metric_events WHERE created_at <
now() - interval 'N days'`` cheap.

Concurrency note: the near-duplicate classifier reads the prior
comment with no locking. Two same-agent comments posted within
microseconds both see the same "prior", so a near-duplicate between
them is unflagged. This is an intentional simplification —
observational metrics don't need strict serialization, and adding
``SELECT FOR UPDATE`` would serialize every comment write on the
task row.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_
from sqlmodel import col, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.activity_events import ActivityEvent
from app.models.shadow_metric_events import ShadowMetricEvent
from app.services.comment_classifier import ClassifierFlag, classify
from app.services.comment_classifier.patterns import (
    NEAR_DUPLICATE_WINDOW_SECONDS,
)

# Skip the classifier on messages longer than this. Regex passes are O(n)
# and jaccard tokenizes the whole body; at ~32KB the per-comment cost
# stays under a millisecond. Beyond that we risk stalling the request
# loop on an adversarial payload. The activity_events row itself still
# stores the full text — the cap is classifier-only.
MESSAGE_CLASSIFY_MAX_CHARS = 32 * 1024

logger = logging.getLogger(__name__)

# Canonical event type constants. Keep these in sync with downstream
# operator dashboards — changing a value rewrites history from the
# operator's POV.
EVENT_COMMENT_ACK_ONLY = "comment.ack_only_candidate"
EVENT_COMMENT_NEAR_DUPLICATE = "comment.near_duplicate_candidate"
EVENT_TASK_ACTIONABILITY_VIOLATION = "task.actionability_violation_candidate"
# Phase V §I8: emitted when a task enters ``review``/``done`` with a
# ``supports_build_metadata`` flag of ``False`` or ``None`` — the
# transition is allowed but validation runs in degraded mode.
# Operators should burn these down by graduating targets to
# capability=True or marking them explicitly blind.
EVENT_TASK_DEPLOY_VALIDATION_DEGRADED = "task.deploy_validation_degraded"
# Phase VI §I6: emitted when a non-owner agent's comment is rejected
# by the lane-quieting gate. Tracks the noise-suppression signal so
# operators can see whether graduated boards are actually producing
# quieter activity feeds.
EVENT_COMMENT_LANE_QUIETING_SUPPRESSED = "comment.lane_quieting_suppressed"
# Phase VI §I5: emitted per scored window where a lead agent produced
# zero real actions (blocker created / task state changed / task
# reassigned). Pure commentary doesn't count. Streak alert fires when
# a lead emits two consecutive candidates — this is the operator-
# alert signal §I5 requires.
EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE = "supervisor.heartbeat_noop_candidate"
EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT = (
    "supervisor.heartbeat_noop_streak_alert"
)
# First-ever scoring for a lead: emit a bootstrap marker so subsequent
# sweeps have a bookmark, without counting the boot-window as a real
# no-op observation (which would falsely chain into a streak alert).
EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP = (
    "supervisor.heartbeat_scoring_bootstrap"
)


async def emit_supervisor_heartbeat_scoring_bootstrap(
    *,
    agent_id: UUID,
    board_id: UUID | None,
    evaluated_at: datetime,
) -> None:
    """First-ever scoring for a lead — writes a bootstrap row so the
    bookmark exists for the next sweep, WITHOUT participating in the
    noop-streak detection. Prevents boot-time spurious alerts.
    """

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP,
                board_id=board_id,
                agent_id=agent_id,
                classifier_metadata={
                    "evaluated_at": evaluated_at.isoformat(),
                },
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        logger.info(
            "shadow_metrics.supervisor_bootstrap_emit_cancelled agent_id=%s",
            agent_id,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.supervisor_bootstrap_emit_failed agent_id=%s",
            agent_id,
        )


async def emit_supervisor_heartbeat_noop_candidate(
    *,
    agent_id: UUID,
    board_id: UUID | None,
    window_started_at: datetime,
) -> None:
    """Record a lead heartbeat window that scored zero real actions."""

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE,
                board_id=board_id,
                agent_id=agent_id,
                classifier_metadata={
                    "window_started_at": window_started_at.isoformat(),
                },
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        logger.info(
            "shadow_metrics.supervisor_noop_candidate_emit_cancelled agent_id=%s",
            agent_id,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.supervisor_noop_candidate_emit_failed agent_id=%s",
            agent_id,
        )


async def emit_supervisor_heartbeat_noop_streak_alert(
    *,
    agent_id: UUID,
    board_id: UUID | None,
    previous_candidate_at: datetime,
) -> None:
    """Fire when a lead produces two consecutive no-op candidates —
    the operator-alert signal §I5 requires."""

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT,
                board_id=board_id,
                agent_id=agent_id,
                classifier_metadata={
                    "previous_candidate_at": previous_candidate_at.isoformat(),
                },
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        logger.info(
            "shadow_metrics.supervisor_noop_streak_emit_cancelled agent_id=%s",
            agent_id,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.supervisor_noop_streak_emit_failed agent_id=%s",
            agent_id,
        )


async def emit_actionability_violation_metric(
    *,
    task_id: UUID | None,
    board_id: UUID | None,
    agent_id: UUID | None,
    status_value: str,
    missing_fields: list[str],
) -> None:
    """Record a delivery-contract violation that the validator is about to raise.

    Uses a dedicated short-lived session rather than the caller's so the
    row survives the caller's transaction rollback (the 422 raise aborts
    whatever write the caller was attempting, but the observability
    signal must persist).

    Fire-and-forget semantics: errors are logged, never propagated. The
    caller's 422 response must not be delayed by this hook.
    """

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_TASK_ACTIONABILITY_VIOLATION,
                task_id=task_id,
                board_id=board_id,
                agent_id=agent_id,
                classifier_metadata={
                    "status_value": status_value,
                    # Defensive copy: the caller may hand us the same list
                    # that will be handed to the raise's error detail; a
                    # background task reading from a mutated reference
                    # would record a different value than the raise.
                    "missing_fields": list(missing_fields),
                },
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        # Shutdown or explicit cancellation. Log separately so operators
        # can distinguish "shadow backlog dropped at shutdown" from a
        # real emitter bug, then propagate so the caller's gather()
        # at lifespan drain sees the correct status.
        logger.info(
            "shadow_metrics.actionability_emit_cancelled task_id=%s status=%s",
            task_id,
            status_value,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.actionability_emit_failed task_id=%s status=%s",
            task_id,
            status_value,
        )


async def emit_lane_quieting_suppressed_metric(
    *,
    task_id: UUID | None,
    board_id: UUID | None,
    agent_id: UUID | None,
) -> None:
    """Record a non-owner comment rejected by the §I6 lane-quieting
    gate. Same fire-and-forget contract as the actionability +
    deploy-degraded emitters.
    """

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_COMMENT_LANE_QUIETING_SUPPRESSED,
                task_id=task_id,
                board_id=board_id,
                agent_id=agent_id,
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        logger.info(
            "shadow_metrics.lane_quieting_emit_cancelled task_id=%s",
            task_id,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.lane_quieting_emit_failed task_id=%s",
            task_id,
        )


async def emit_deploy_validation_degraded_metric(
    *,
    task_id: UUID | None,
    board_id: UUID | None,
    agent_id: UUID | None,
    status_value: str,
    reason: str,
) -> None:
    """Record that a ``review``/``done`` transition ran without live
    SHA verification. Same fire-and-forget contract as the
    actionability emitter — errors logged, never propagated.
    """

    try:
        async with async_session_maker() as session:
            event = ShadowMetricEvent(
                event_type=EVENT_TASK_DEPLOY_VALIDATION_DEGRADED,
                task_id=task_id,
                board_id=board_id,
                agent_id=agent_id,
                classifier_metadata={
                    "status_value": status_value,
                    "reason": reason,
                },
            )
            session.add(event)
            await session.commit()
    except asyncio.CancelledError:
        logger.info(
            "shadow_metrics.deploy_degraded_emit_cancelled task_id=%s status=%s",
            task_id,
            status_value,
        )
        raise
    except Exception:
        logger.exception(
            "shadow_metrics.deploy_degraded_emit_failed task_id=%s status=%s",
            task_id,
            status_value,
        )


def _flag_to_event_type(flag: ClassifierFlag) -> str:
    if flag is ClassifierFlag.ACK_ONLY:
        return EVENT_COMMENT_ACK_ONLY
    if flag is ClassifierFlag.NEAR_DUPLICATE:
        return EVENT_COMMENT_NEAR_DUPLICATE
    raise ValueError(f"Unknown classifier flag: {flag!r}")


async def _fetch_prior_comment(
    session: AsyncSession,
    *,
    task_id: UUID,
    agent_id: UUID,
    since: datetime,
) -> ActivityEvent | None:
    """Most recent comment by ``agent_id`` on ``task_id`` at or after ``since``.

    PG uses the partial index
    ``ix_activity_events_task_comment_task_id_created_at`` on
    ``(task_id, created_at) WHERE event_type='task.comment'`` from
    ``99cd6df95f85`` to range-scan on task_id, then filters agent_id in
    the heap. Selective enough at per-task comment volumes.
    """

    statement = (
        select(ActivityEvent)
        .where(
            and_(
                col(ActivityEvent.task_id) == task_id,
                col(ActivityEvent.agent_id) == agent_id,
                col(ActivityEvent.event_type) == "task.comment",
                col(ActivityEvent.created_at) >= since,
            )
        )
        .order_by(desc(col(ActivityEvent.created_at)))
        .limit(1)
    )
    return (await session.exec(statement)).first()


@dataclass(frozen=True, slots=True)
class CommentClassifierResult:
    """Output of the comment classifier hook.

    Separates the flag list (used to stamp classifier_flags on the
    ActivityEvent row for fast GET filtering) from the shadow events
    (long-term observability storage). Both commit atomically via the
    caller's session.

    ``classifier_ran=True`` means ``classify()`` returned a definitive
    answer (empty or populated). The caller stamps ``classifier_flags``
    accordingly: ``[]`` when flags=[] (observable "clean"), the list
    when flagged.

    ``classifier_ran=False`` collapses every "no definitive answer"
    case — the comment was skipped because the agent_id was None,
    skipped because the body exceeded MESSAGE_CLASSIFY_MAX_CHARS, or
    ``classify()`` itself raised and the builder caught it. All three
    surface in the DB as ``classifier_flags IS NULL``. Callers that
    need to distinguish among them grep the ``shadow_metrics.*``
    log lines. The column itself intentionally does not encode the
    reason; the operator runbook says NULL means "don't treat this row
    as classifier evidence either way".
    """

    flags: list[ClassifierFlag]
    shadow_events: list[ShadowMetricEvent]
    classifier_ran: bool


async def build_shadow_events_for_comment(
    session: AsyncSession,
    *,
    task_id: UUID,
    board_id: UUID | None,
    agent_id: UUID | None,
    source_event_id: UUID,
    message: str,
    packet_type: str | None,
    now: datetime | None = None,
) -> CommentClassifierResult:
    """Classify a new comment.

    Must be called BEFORE the new comment's ``ActivityEvent`` is added
    to the session so the prior-comment query does not see it.

    Returns a ``CommentClassifierResult`` with:
    - ``flags``: the list of ClassifierFlag values to stamp on the
      comment's ActivityEvent.classifier_flags column.
    - ``shadow_events``: one ShadowMetricEvent per flag for the
      append-only observability table.
    """

    skipped = CommentClassifierResult(flags=[], shadow_events=[], classifier_ran=False)

    # User-authored comments (no agent_id) are exempt from ack-theater
    # classification. The observability surface measures agent noise;
    # treating operator acks as data points pollutes the histogram.
    if agent_id is None:
        return skipped

    # Defensive cap on pathological payloads — see MESSAGE_CLASSIFY_MAX_CHARS.
    if len(message) > MESSAGE_CLASSIFY_MAX_CHARS:
        logger.info(
            "shadow_metrics.message_too_long_skipped task_id=%s agent_id=%s length=%d",
            task_id,
            agent_id,
            len(message),
        )
        return skipped

    reference = now if now is not None else utcnow()
    window_start = reference - timedelta(seconds=NEAR_DUPLICATE_WINDOW_SECONDS)
    # DB failures must fail the whole request, not silently lose signal:
    # the caller's commit would fail on the same broken session anyway,
    # so silent fallback here only hides the incident signal.
    prior = await _fetch_prior_comment(
        session,
        task_id=task_id,
        agent_id=agent_id,
        since=window_start,
    )
    prior_message = prior.message if prior is not None else None
    prior_created_at = prior.created_at if prior is not None else None

    # classify() is pure regex/jaccard — unexpected raises indicate a real
    # code bug, not an operational failure. Keep a narrow guard so a bad
    # input doesn't break comment writes, but still surface the exception.
    try:
        flags = classify(
            message,
            packet_type=packet_type,
            prior_comment=prior_message,
            prior_comment_created_at=prior_created_at,
            now=reference,
        )
    except Exception:
        logger.exception(
            "shadow_metrics.classify_raised task_id=%s agent_id=%s",
            task_id,
            agent_id,
        )
        return skipped

    if not flags:
        return CommentClassifierResult(flags=[], shadow_events=[], classifier_ran=True)

    shadow_events = [
        ShadowMetricEvent(
            event_type=_flag_to_event_type(flag),
            task_id=task_id,
            agent_id=agent_id,
            board_id=board_id,
            source_event_id=source_event_id,
            classifier_metadata={
                "packet_type": packet_type,
                "message_length": len(message),
            },
        )
        for flag in flags
    ]
    return CommentClassifierResult(
        flags=list(flags),
        shadow_events=shadow_events,
        classifier_ran=True,
    )
