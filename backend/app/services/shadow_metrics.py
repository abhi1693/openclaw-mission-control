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

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_
from sqlmodel import col, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
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
) -> list[ShadowMetricEvent]:
    """Classify a new comment and return shadow-metric events for it.

    Must be called BEFORE the new comment's ``ActivityEvent`` is added
    to the session so the prior-comment query does not see it.
    """

    # User-authored comments (no agent_id) are exempt from ack-theater
    # classification. The observability surface measures agent noise;
    # treating operator acks as data points pollutes the histogram.
    if agent_id is None:
        return []

    # Defensive cap on pathological payloads — see MESSAGE_CLASSIFY_MAX_CHARS.
    if len(message) > MESSAGE_CLASSIFY_MAX_CHARS:
        logger.info(
            "shadow_metrics.message_too_long_skipped task_id=%s agent_id=%s length=%d",
            task_id,
            agent_id,
            len(message),
        )
        return []

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
        return []

    if not flags:
        return []

    return [
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
