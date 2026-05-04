"""Service helpers for Phase II blocker-aware task queries (plan §I1).

The ``is_blocked`` derivation on ``TaskRead`` now needs to check for
any open ``Blocker`` row in addition to the legacy
``depends_on_task_ids`` + operator-decision signals. Per-row lookups
would N+1 on task list endpoints, so this module provides a batched
fetch for the list/stream paths and a scalar EXISTS for single-task
reads.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import exists
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.blockers import Blocker
from app.services.blocker_reason_codes import group_codes_by_task

# Reason codes that the system emits on the lead path when pipeline
# events are missing for a task. AC5 incident at 2026-05-02 01:39 UTC
# showed why these need machine-owned resolution: the lead opens them,
# the worker fills the missing pipeline events, and without an explicit
# resolver the Blocker stays open forever (and ``is_blocked=True`` stays
# with it). Manual / operator-decision Blockers are NEVER in this set —
# those require explicit human resolution.
PIPELINE_AUTO_RESOLVE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "pipeline_missing_review_gate",
        "in_progress_pipeline_missing_review_gate",
    },
)


async def task_ids_with_open_blocker(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> set[UUID]:
    """Return the subset of the given task ids that have any open blocker.

    "Open" means ``resolved_at IS NULL``. The board_id filter keeps
    the query tenant-scoped and lets the partial
    ``ix_blockers_board_id_task_id_open`` index drive both the
    lookup and the IN filter on Postgres.
    """

    task_id_list = list(task_ids)
    if not task_id_list:
        return set()
    stmt = (
        select(col(Blocker.task_id))
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id).in_(task_id_list))
        .where(col(Blocker.resolved_at).is_(None))
    )
    return set((await session.exec(stmt)).all())


async def open_blocker_rows_by_task_id(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> dict[UUID, list[tuple[UUID, str | None, str | None, UUID | None, datetime, datetime | None]]]:
    """Batched projection of open Blockers grouped by task_id.

    Each value is a list of
    ``(blocker_id, reason_code, owner_role, acknowledged_by_agent_id, created_at, acknowledged_at)``
    tuples ordered by ``created_at`` ascending so the caller can pick
    the oldest blocker without re-sorting.

    ``acknowledged_at`` lets the lead's stale-blocker tier reset its
    clock on owner acknowledgement: once the owner has explicitly
    claimed the blocker, the lead waits another grace window before
    re-nudging.

    Used by the lead next-action endpoint to feed the new
    ``open_blockers_by_task_id`` parameter for the stale-blocker tier
    in one SQL pass — without this, the tier would need a per-task
    SELECT and N+1 the endpoint.
    """
    task_id_list = list(task_ids)
    if not task_id_list:
        return {}
    stmt = (
        select(
            col(Blocker.task_id),
            col(Blocker.id),
            col(Blocker.reason_code),
            col(Blocker.owner_role),
            col(Blocker.acknowledged_by_agent_id),
            col(Blocker.created_at),
            col(Blocker.acknowledged_at),
        )
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id).in_(task_id_list))
        .where(col(Blocker.resolved_at).is_(None))
        .order_by(col(Blocker.task_id), col(Blocker.created_at))
    )
    grouped: dict[UUID, list[tuple[UUID, str | None, str | None, UUID | None, datetime, datetime | None]]] = {}
    for row in (await session.exec(stmt)).all():
        task_id, blocker_id, reason_code, owner_role, owner_agent_id, created_at, acknowledged_at = row
        grouped.setdefault(task_id, []).append(
            (blocker_id, reason_code, owner_role, owner_agent_id, created_at, acknowledged_at),
        )
    return grouped


async def task_has_open_blocker(
    session: AsyncSession, *, board_id: UUID, task_id: UUID
) -> bool:
    """Single-task EXISTS — cheaper than pulling the id set for the
    PATCH response path where we only need a boolean."""

    stmt = select(
        exists()
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id) == task_id)
        .where(col(Blocker.resolved_at).is_(None))
    )
    result = await session.exec(stmt)
    return bool(result.first())


async def auto_resolve_pipeline_blockers_if_ready(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> int:
    """Resolve system-authored pipeline Blockers when pipeline.ready=true.

    Fires from two call sites — pipeline-event create and Blocker create
    — to close the AC5-shaped failure mode: pipeline events arrive that
    satisfy the unblock condition, but the Blocker entity itself stays
    open because nothing knows how to map "pipeline ready" back to
    "Blocker resolved." Manual blockers (operator_policy, content
    gates, etc.) are out of scope; only reason codes in
    ``PIPELINE_AUTO_RESOLVE_REASON_CODES`` qualify.

    **Cycle scope:** events are filtered by the task's current cycle
    (``task.in_progress_at`` or ``task.previous_in_progress_at``).
    Without this, a stale set of events from a prior review cycle
    (already done/rejected, then sent back to rework) would falsely
    satisfy ``pipeline.ready`` for a new-cycle Blocker, producing the
    inverse of the AC5 failure (auto-resolving a still-blocked task).
    Same cycle window the lead's missing-state calc uses.

    Returns the number of Blockers resolved (0 when nothing to do).
    The caller is responsible for ``session.commit()`` afterwards if
    the count is non-zero — keeping commit out of this helper lets
    callers batch with their own transaction work.
    """
    from app.models.tasks import Task
    from app.services.task_pipeline import (
        list_task_pipeline_events,
        pipeline_missing_states,
    )

    # System-authored signal: only auto-resolve Blockers whose
    # ``created_by_agent_id`` matches a current board-lead agent. The
    # API allows arbitrary ``reason_code`` values on POST /blockers,
    # so an operator could file a manual Blocker with one of the
    # pipeline reason codes as their own workflow signal — codex
    # 2026-05-02 holistic review caught that resolving those silently
    # would be a permission inversion. Restricting to lead authorship
    # keeps the AC5 repro (lead's ``inspect_stale_in_progress`` /
    # materialization paths emit these) while letting operator-filed
    # blockers remain manually-resolved.
    from app.models.agents import Agent

    lead_ids_stmt = select(col(Agent.id)).where(
        col(Agent.board_id) == board_id,
    ).where(col(Agent.is_board_lead).is_(True))
    lead_ids = list((await session.exec(lead_ids_stmt)).all())

    open_blockers_stmt = (
        select(Blocker)
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id) == task_id)
        .where(col(Blocker.resolved_at).is_(None))
        .where(col(Blocker.reason_code).in_(PIPELINE_AUTO_RESOLVE_REASON_CODES))
    )
    if lead_ids:
        open_blockers_stmt = open_blockers_stmt.where(
            col(Blocker.created_by_agent_id).in_(lead_ids),
        )
    else:
        # No lead → nothing is system-authored on this board.
        return 0
    open_blockers = list((await session.exec(open_blockers_stmt)).all())
    if not open_blockers:
        return 0

    task = (
        await session.exec(select(Task).where(col(Task.id) == task_id))
    ).first()
    if task is None:
        return 0
    cycle_since = task.in_progress_at or task.previous_in_progress_at
    events = await list_task_pipeline_events(
        session, task_id=task_id, since=cycle_since
    )
    if pipeline_missing_states(events):
        # Pipeline still has missing required states for the current
        # cycle — keep Blockers open.
        return 0

    now = utcnow()
    for blocker in open_blockers:
        blocker.resolved_at = now
        session.add(blocker)
    return len(open_blockers)


async def open_blocker_summary_for_task(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> list[tuple[UUID, str | None]]:
    """Return ``[(blocker_id, reason_code), ...]`` for all open blockers on a task.

    Used by the PATCH transition guard so the 409 response can name
    which blockers are holding the task. Returns an empty list when
    no open blockers exist. Reason codes may be None for legacy rows
    written before reason_code was required; the guard surfaces the
    blocker id either way so the operator can resolve it.
    """
    stmt = (
        select(col(Blocker.id), col(Blocker.reason_code))
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id) == task_id)
        .where(col(Blocker.resolved_at).is_(None))
        .order_by(col(Blocker.created_at))
    )
    return [(row[0], row[1]) for row in (await session.exec(stmt)).all()]


async def open_blocker_reason_codes_by_task_id(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> dict[UUID, list[str]]:
    """Return non-null open-blocker reason codes grouped by task id.

    Lets the agent task scan endpoint expose ``reason_code`` per task in
    one batched query — without it the Supervisor's ``lead-health-scan``
    skill would N+1 the blocker rows to find revalidation candidates.
    Tasks whose only open blockers carry ``reason_code IS NULL`` are
    absent from the result map.
    """
    task_id_list = list(task_ids)
    if not task_id_list:
        return {}
    stmt = (
        select(col(Blocker.task_id), col(Blocker.reason_code))
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id).in_(task_id_list))
        .where(col(Blocker.resolved_at).is_(None))
        .where(col(Blocker.reason_code).is_not(None))
    )
    return group_codes_by_task((await session.exec(stmt)).all())
