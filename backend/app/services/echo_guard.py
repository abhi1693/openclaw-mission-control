"""Phase VII comment-echo write gate.

Rejects low-delta same-author comments that carry the ECHO_SHAPE
classifier signal AND have a recent same-author prior on the same task
AND have seen no state change since that prior.

Motivation: the 2026-04-17 22:30 UTC Architect↔Supervisor echo storm
produced 40 near-identical "Acknowledged / Confirmed — nothing changed,
we agree" comments on one task in 10 minutes. The existing ack-only
classifier missed the Architect half (leading ``@mentions`` broke the
regex), and near-duplicate detection missed both halves (jaccard ~0.42,
below the 0.90 threshold). Phase VII extends the classifier (see
``ECHO_SHAPE`` in ``app/services/comment_classifier/classifier.py``)
and adds this service as the write-side enforcement.

Three-signal intersection:

1. **Shape** — the message fires the ECHO_SHAPE classifier flag
   (covers the extended ack-head + state-reassurance phrases that the
   2026-04-17 storm used).
2. **Repeat** — the same agent has a same-task comment within the last
   ``ECHO_GUARD_WINDOW_SECONDS``.
3. **No-state-delta** — no ``Blocker`` was created or resolved on the
   task between that prior comment and now.

The AND-of-three gating keeps false-positives low — a first-ever
alignment message on a new task never trips (no prior), and a later
comment that legitimately acknowledges a freshly-filed blocker never
trips (state delta via new blocker). It does not try to detect every
possible echo — the loop's bankroll is the tight cadence on an
unchanged task, and that's what the AND catches.

Enforcement vs observe is per-board via
``comment_echo_guard_v1`` rollout flag. Same ``board_rollout_flag_enabled``
helper every other Phase 0+ gate uses. When off, callers may still
read the predicate and emit shadow metrics for rollout tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import exists as sql_exists
from sqlmodel import col, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.boards import (
    COMMENT_ECHO_GUARD_V1_FLAG,
    board_rollout_flag_enabled,
)
from app.services.comment_classifier import ClassifierFlag, classify

logger = get_logger(__name__)

# Thirty minutes matches the heartbeat cadence — anything farther apart
# than that is two independent decisions to comment, not an echo.
ECHO_GUARD_WINDOW_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class EchoGuardResult:
    """Outcome of ``classify_for_echo``.

    ``should_suppress`` is the boolean the ingress gate acts on when
    the rollout flag is enabled. ``classifier_flags`` preserves the
    full classifier output so callers can still stamp
    ``ActivityEvent.classifier_flags`` on the row when the gate is in
    observe-mode.
    """

    should_suppress: bool
    classifier_flags: list[ClassifierFlag]
    reason: str | None


async def _fetch_prior_same_author_comment(
    session: AsyncSession,
    *,
    task_id: UUID,
    agent_id: UUID,
    window_start: datetime,
) -> ActivityEvent | None:
    """Most recent same-author comment on the same task inside the
    echo-guard window."""

    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task_id)
        .where(col(ActivityEvent.agent_id) == agent_id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.created_at) >= window_start)
        .order_by(desc(col(ActivityEvent.created_at)))
        .limit(1)
    )
    return (await session.exec(statement)).first()


async def _blocker_changed_since(
    session: AsyncSession,
    *,
    task_id: UUID,
    since: datetime,
) -> bool:
    """True when any ``Blocker`` row on the task was created or
    resolved after ``since``. A state delta that should re-open the
    lane for commentary."""

    changed = await session.scalar(
        select(
            sql_exists()
            .where(col(Blocker.task_id) == task_id)
            .where((col(Blocker.created_at) > since) | (col(Blocker.resolved_at) > since))
        )
    )
    return bool(changed)


async def classify_for_echo(
    session: AsyncSession,
    *,
    task: Task,
    agent_id: UUID | None,
    message: str,
) -> EchoGuardResult:
    """Evaluate the three-signal gate.

    Returns an ``EchoGuardResult`` whose ``should_suppress`` is
    ``True`` only when the board has graduated
    ``comment_echo_guard_v1``, the classifier flagged the message as
    ECHO_SHAPE, a recent same-author prior exists, and no
    state-delta (blocker create/resolve) happened on the task
    between that prior and now. User-token callers
    (``agent_id is None``) are always exempt — human operators are
    not subject to the echo gate.
    """

    packet_type = task.review_packet_type

    if agent_id is None or task.board_id is None:
        flags = classify(message, packet_type=packet_type)
        return EchoGuardResult(should_suppress=False, classifier_flags=flags, reason=None)

    now = utcnow()
    window_start = now - timedelta(seconds=ECHO_GUARD_WINDOW_SECONDS)

    prior = await _fetch_prior_same_author_comment(
        session,
        task_id=task.id,
        agent_id=agent_id,
        window_start=window_start,
    )

    flags = classify(
        message,
        packet_type=packet_type,
        prior_comment=prior.message if prior is not None else None,
        prior_comment_created_at=prior.created_at if prior is not None else None,
        now=now,
    )

    if prior is None:
        # First comment in the window — no echo possible by definition.
        return EchoGuardResult(should_suppress=False, classifier_flags=flags, reason=None)

    if ClassifierFlag.ECHO_SHAPE not in flags:
        return EchoGuardResult(should_suppress=False, classifier_flags=flags, reason=None)

    if await _blocker_changed_since(session, task_id=task.id, since=prior.created_at):
        # Legitimate alignment after a fresh blocker was filed/resolved.
        return EchoGuardResult(should_suppress=False, classifier_flags=flags, reason=None)

    board_flags = await session.scalar(
        select(Board.rollout_flags).where(col(Board.id) == task.board_id)
    )
    if not board_rollout_flag_enabled(board_flags, COMMENT_ECHO_GUARD_V1_FLAG):
        # Shadow-mode: classifier fired but enforcement is off.
        return EchoGuardResult(should_suppress=False, classifier_flags=flags, reason="observe")

    logger.info(
        "echo_guard.suppress task_id=%s agent_id=%s prior_at=%s flags=%s",
        task.id,
        agent_id,
        prior.created_at,
        [f.value for f in flags],
    )
    return EchoGuardResult(
        should_suppress=True,
        classifier_flags=flags,
        reason="echo_shape_no_state_delta",
    )
