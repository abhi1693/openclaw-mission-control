"""Phase VI §I5 lead heartbeat no-op scoring.

A lead heartbeat only scores as success if it produced at least one
of the four action categories the plan enumerates. Commentary alone
is a no-op; two consecutive no-op scorings trigger the operator
alert.

Attribution strategy (v1, three of four categories):
- ``Blocker`` rows where ``created_by_agent_id`` matches the lead
  (clean attribution via Phase II).
- ``ActivityEvent`` rows with ``event_type`` in the mutation set
  below AND ``agent_id`` matching the lead.

The "dependency graph changed" category is deferred — ``task_dependencies``
currently has no ``created_by`` column, so attribution would be
noisy. v2 can add that column and expand the scoring.

Bookmark strategy: derived from shadow_metric_events. ``last_scored_at``
is ``MAX(created_at)`` over the noop-candidate + streak-alert event
types for the lead. No new state columns — the metric table IS the
truth. Matches the A+X choice from the design brainstorm.

Streak detection: before emitting a candidate, read whether the most
recent prior candidate for the lead is within the last sweep window
(2× configured interval gives us "consecutive heartbeats" tolerance
even if one sweep pass was skipped). If yes, emit the streak-alert
row alongside the candidate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import exists
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.shadow_metric_events import ShadowMetricEvent
from app.schemas.boards import LEAD_SCORING_V1_FLAG, board_rollout_flag_enabled
from app.services.shadow_metrics import (
    EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE,
    EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT,
    EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP,
    emit_supervisor_heartbeat_noop_candidate,
    emit_supervisor_heartbeat_noop_streak_alert,
    emit_supervisor_heartbeat_scoring_bootstrap,
)

logger = get_logger(__name__)

# ActivityEvent types that count as real mutations by the lead. We
# deliberately exclude ``task.comment`` (commentary is the no-op
# §I5 wants to catch) and ``*_notified`` / ``*_wake_*`` side-effect
# types (those are byproducts, not lead-authored actions).
_LEAD_ACTION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # ``task.created`` is omitted because ``create_task`` is a
        # USER_AUTH_DEP path — the agent_id on those events is always
        # NULL, so counting them would credit no lead anyway. Leads
        # act by PATCHing existing tasks, which emits task.updated
        # and task.status_changed.
        "task.updated",
        "task.status_changed",
    }
)


async def lead_has_any_action_since(
    session: AsyncSession,
    *,
    agent_id: UUID,
    board_id: UUID,
    bookmark: datetime,
) -> bool:
    """True if the lead has any blocker- or task-mutation activity
    since ``bookmark``. EXISTS short-circuits at the first match so we
    don't pay a full COUNT on a chatty lane.
    """

    has_blocker = await session.scalar(
        select(
            exists()
            .where(col(Blocker.board_id) == board_id)
            .where(col(Blocker.created_by_agent_id) == agent_id)
            .where(col(Blocker.created_at) > bookmark)
        )
    )
    if has_blocker:
        return True
    has_activity = await session.scalar(
        select(
            exists()
            .where(col(ActivityEvent.board_id) == board_id)
            .where(col(ActivityEvent.agent_id) == agent_id)
            .where(col(ActivityEvent.event_type).in_(_LEAD_ACTION_EVENT_TYPES))
            .where(col(ActivityEvent.created_at) > bookmark)
        )
    )
    return bool(has_activity)


async def count_lead_actions_since(
    session: AsyncSession,
    *,
    agent_id: UUID,
    board_id: UUID,
    bookmark: datetime,
) -> int:
    """Legacy test-helper shape. Returns 0 or 1 based on EXISTS."""

    return (
        1
        if await lead_has_any_action_since(
            session,
            agent_id=agent_id,
            board_id=board_id,
            bookmark=bookmark,
        )
        else 0
    )


_SCORING_EVENT_TYPES = frozenset(
    {
        EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE,
        EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT,
        EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP,
    }
)


async def last_scoring_bookmark(session: AsyncSession, *, agent_id: UUID) -> datetime | None:
    """Return the most-recent scoring timestamp for the lead, or None
    if they've never been scored. Reads from shadow_metric_events so
    no new state columns are needed — the event table is the truth.
    Includes the bootstrap-event type so warmup counts as a bookmark.
    """

    return await session.scalar(
        select(func.max(col(ShadowMetricEvent.created_at)))
        .where(col(ShadowMetricEvent.agent_id) == agent_id)
        .where(col(ShadowMetricEvent.event_type).in_(_SCORING_EVENT_TYPES))
    )


async def _previous_noop_candidate_at(
    session: AsyncSession,
    *,
    agent_id: UUID,
    cutoff: datetime,
) -> datetime | None:
    """Return the timestamp of the most-recent prior noop-candidate
    event for the lead, restricted to the given cutoff window. Used
    to decide whether this sweep's candidate constitutes a streak."""

    return await session.scalar(
        select(func.max(col(ShadowMetricEvent.created_at)))
        .where(col(ShadowMetricEvent.agent_id) == agent_id)
        .where(col(ShadowMetricEvent.event_type) == EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE)
        .where(col(ShadowMetricEvent.created_at) >= cutoff)
    )


async def score_lead_once(
    session: AsyncSession,
    *,
    agent: Agent,
    board_id: UUID,
    sweep_interval: timedelta,
    now: datetime | None = None,
) -> bool:
    """Score one lead and emit metrics. Returns True if a no-op
    candidate was emitted (the lead did nothing in the window).

    ``sweep_interval`` is used to size the streak-detection lookback
    window (2× the interval) so a single dropped sweep doesn't reset
    the streak. The sweeper passes the configured interval through.
    """

    evaluated_at = now or utcnow()
    bookmark = await last_scoring_bookmark(session, agent_id=agent.id)

    # Warmup grace: the very first scoring for a lead writes a
    # bootstrap marker so the bookmark exists for the next sweep
    # WITHOUT participating in streak detection. This prevents a
    # boot-time deploy-downtime window from chaining into a spurious
    # streak alert. Bootstrap events are included in
    # ``last_scoring_bookmark`` but excluded from
    # ``_previous_noop_candidate_at``.
    if bookmark is None:
        await emit_supervisor_heartbeat_scoring_bootstrap(
            agent_id=agent.id,
            board_id=board_id,
            evaluated_at=evaluated_at,
        )
        return False

    # Capture the prior-candidate timestamp BEFORE emitting this
    # sweep's candidate — otherwise the streak lookup would find its
    # own freshly-written row and fire an alert on the first sweep.
    # 2× interval tolerates one dropped sweep in between.
    streak_cutoff = evaluated_at - (sweep_interval * 2)
    previous_candidate_at = await _previous_noop_candidate_at(
        session,
        agent_id=agent.id,
        cutoff=streak_cutoff,
    )

    if await lead_has_any_action_since(
        session,
        agent_id=agent.id,
        board_id=board_id,
        bookmark=bookmark,
    ):
        return False

    await emit_supervisor_heartbeat_noop_candidate(
        agent_id=agent.id,
        board_id=board_id,
        window_started_at=bookmark,
    )

    if previous_candidate_at is not None:
        await emit_supervisor_heartbeat_noop_streak_alert(
            agent_id=agent.id,
            board_id=board_id,
            previous_candidate_at=previous_candidate_at,
        )
    return True


async def score_all_leads_once(
    session: AsyncSession,
    *,
    sweep_interval: timedelta,
    now: datetime | None = None,
) -> int:
    """Score every lead agent on a board where ``lead_scoring_v1``
    is enabled. Returns the number of no-op candidates emitted."""

    evaluated_at = now or utcnow()
    # Join leads to their boards + pull rollout_flags in the same
    # query so we don't N+1 a per-lead SELECT for the flag check.
    stmt = (
        select(Agent, col(Board.id), col(Board.rollout_flags))
        .join(Board, col(Agent.board_id) == col(Board.id))
        .where(col(Agent.is_board_lead).is_(True))
    )
    rows = (await session.exec(stmt)).all()
    emitted = 0
    for agent, board_id, board_flags in rows:
        if not board_rollout_flag_enabled(board_flags, LEAD_SCORING_V1_FLAG):
            continue
        try:
            fired = await score_lead_once(
                session,
                agent=agent,
                board_id=board_id,
                sweep_interval=sweep_interval,
                now=evaluated_at,
            )
        except Exception:
            # A slow DB or a transient emit failure must not kill the
            # whole sweep. Log and continue so a single bad lead
            # doesn't starve the rest.
            logger.exception(
                "lead_scoring.score_once_failed agent_id=%s board_id=%s",
                agent.id,
                board_id,
            )
            continue
        if fired:
            emitted += 1
    return emitted
