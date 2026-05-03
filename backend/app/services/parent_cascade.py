"""Parent-child cascade helpers for the Phase V decomposition link.

When a parent task reaches a terminal state (``done``/``cancelled``),
its non-terminal children become *orphans* — work items whose
reason-for-being just evaporated. Conversely, when the LAST non-terminal
child of a never-executed parent reaches terminal status, the parent
itself can be retired (umbrella auto-cascade).

Read helpers (``orphan_*``, ``task_ids_with_*``) are pure projections
for the lead-next-action gate. The mutating ``maybe_cascade_umbrella_close``
fires from the PATCH endpoint after a terminal status transition; it
auto-cancels never-executed parents whose children are all terminal.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.tasks import Task
from app.services.activity_log import record_activity

logger = logging.getLogger(__name__)

TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})
# Decomposition depth in practice is 2-3 levels (umbrella -> phase ->
# track). 10 is generous and bounds runaway recursion if a cycle ever
# slips into ``parent_task_id`` (no DB-level DAG enforcement).
_UMBRELLA_CASCADE_MAX_DEPTH: int = 10


async def non_terminal_children_of(
    session: AsyncSession,
    *,
    board_id: UUID,
    parent_task_id: UUID,
) -> list[UUID]:
    """Return the ids of non-terminal children of the given parent.

    Order is stable by ``created_at`` so callers can quote a
    deterministic list in activity-event messages.
    """
    stmt = (
        select(col(Task.id))
        .where(col(Task.board_id) == board_id)
        .where(col(Task.parent_task_id) == parent_task_id)
        .where(col(Task.status).not_in(TERMINAL_STATUSES))
        .order_by(col(Task.created_at).asc())
    )
    return list((await session.exec(stmt)).all())


async def orphan_children_by_parent_id(
    session: AsyncSession,
    *,
    board_id: UUID,
    parent_task_ids: Iterable[UUID],
) -> dict[UUID, list[UUID]]:
    """Return non-terminal children grouped by parent id (batch).

    Mirrors the shape of ``open_blocker_reason_codes_by_task_id`` —
    parents whose children are all terminal are absent from the
    result map (no empty lists). Designed for the
    ``TaskCardRead``/``TaskRead`` enrichment path where dozens of
    parents may need their orphan list in a single query.
    """
    parent_ids = list(parent_task_ids)
    if not parent_ids:
        return {}
    stmt = (
        select(col(Task.parent_task_id), col(Task.id))
        .where(col(Task.board_id) == board_id)
        .where(col(Task.parent_task_id).in_(parent_ids))
        .where(col(Task.status).not_in(TERMINAL_STATUSES))
        .order_by(col(Task.created_at).asc())
    )
    grouped: defaultdict[UUID, list[UUID]] = defaultdict(list)
    for parent_id, child_id in (await session.exec(stmt)).all():
        if parent_id is None:
            continue
        grouped[parent_id].append(child_id)
    return dict(grouped)


_UMBRELLA_RETIRED_MARKER_PATTERN = re.compile(r"^\s*UMBRELLA_RETIRED\b", re.MULTILINE)


async def task_ids_with_umbrella_retired_marker(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> frozenset[UUID]:
    """Return the subset of ``task_ids`` carrying an ``UMBRELLA_RETIRED`` comment.

    The marker is posted by the lead per ``lead-inbox-routing``'s
    Umbrella Lifecycle when a pure-container parent has been
    decomposed into subtasks. Once present, the lead's job on this
    umbrella is done — re-firing ``materialize_decomposition_plan``
    would be wasteful (and noisy on pre-Phase-V umbrellas where the
    children predate ``parent_task_id`` and so don't show up in
    ``task_ids_with_children``). This helper provides the secondary
    idempotency signal.

    Marker recognition: anchored at the start of a comment line (with
    optional leading whitespace), word-boundary after. A conversational
    mention like ``"this is NOT an UMBRELLA_RETIRED case"`` does NOT
    qualify — only the canonical ``UMBRELLA_RETIRED:`` prefix counts.
    """
    from app.models.activity_events import ActivityEvent  # local — avoid circular

    task_id_list = list(task_ids)
    if not task_id_list:
        return frozenset()
    # SQL pre-filter narrows by substring; Python regex enforces the
    # anchored canonical prefix to reject conversational mentions.
    stmt = (
        select(col(ActivityEvent.task_id), col(ActivityEvent.message))
        .where(col(ActivityEvent.board_id) == board_id)
        .where(col(ActivityEvent.task_id).in_(task_id_list))
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.message).is_not(None))
        .where(col(ActivityEvent.message).contains("UMBRELLA_RETIRED"))
    )
    matched: set[UUID] = set()
    for task_id, message in (await session.exec(stmt)).all():
        if task_id is None or message is None:
            continue
        if _UMBRELLA_RETIRED_MARKER_PATTERN.search(message):
            matched.add(task_id)
    return frozenset(matched)


async def task_ids_with_children(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> frozenset[UUID]:
    """Return the subset of ``task_ids`` that have at least one child task.

    "Child" means any task on the same board with
    ``parent_task_id == this task's id`` regardless of the child's
    status. Used by the lead next-action gate to distinguish
    decomposition parents that have already been materialized
    (subtasks created) from those still awaiting Supervisor pickup
    after the assignee posted a plan.
    """
    parent_id_list = list(task_ids)
    if not parent_id_list:
        return frozenset()
    stmt = (
        select(col(Task.parent_task_id))
        .where(col(Task.board_id) == board_id)
        .where(col(Task.parent_task_id).in_(parent_id_list))
        .distinct()
    )
    return frozenset(
        parent_id for parent_id in (await session.exec(stmt)).all()
        if parent_id is not None
    )


async def maybe_cascade_umbrella_close(
    session: AsyncSession,
    *,
    task: Task,
) -> Task | None:
    """Auto-cancel a never-executed parent when its last child terminates.

    Fires from ``_finalize_updated_task`` and ``_apply_lead_task_update``
    after a status transition into ``TERMINAL_STATUSES``. Walks up the
    parent chain: if grandparent is also a retired umbrella whose only
    remaining child was the parent we just cancelled, cascade again.
    Returns the topmost parent that was cancelled, or None if no cascade
    fired.

    **Why ``cancelled`` (not ``done``):** the umbrella never executed,
    its work shipped via children. ``done`` claims completion of
    work-on-this-row (false); ``cancelled`` says "no longer needs to
    happen here" (true).

    **Safety net** — the cascade only fires when
    ``parent.in_progress_at IS NULL AND parent.previous_in_progress_at IS NULL``
    AND the parent carries an explicit ``UMBRELLA_RETIRED`` marker
    comment. The marker is the lead's commitment that the parent is
    decomposition-completed.

    **Depth limit** — recursion stops at ``_UMBRELLA_CASCADE_MAX_DEPTH``
    levels so a pathological ``parent_task_id`` cycle (DB does not
    enforce DAG) cannot loop unbounded. When the cap fires, an audit
    activity event is recorded so operators can see the truncation.

    Caller must ``session.commit()`` if the result is non-None.
    """
    if task.status not in TERMINAL_STATUSES:
        return None
    cursor: Task = task
    topmost_cancelled: Task | None = None
    # Iterative walk caps depth without exposing a kwarg an external
    # caller could pass to bypass it. Each loop step closes one parent
    # (if it qualifies) and advances to that parent for the next round.
    for _ in range(_UMBRELLA_CASCADE_MAX_DEPTH):
        parent = await _qualifying_umbrella_parent(session, task=cursor)
        if parent is None:
            return topmost_cancelled
        parent.status = "cancelled"
        parent.cancelled_at = utcnow()
        parent.updated_at = parent.cancelled_at
        session.add(parent)
        record_activity(
            session,
            event_type="task.umbrella_auto_cascaded",
            task_id=parent.id,
            board_id=parent.board_id,
            message=(
                f"Parent auto-cancelled by umbrella cascade after child "
                f"{cursor.id} reached status={cursor.status}; all siblings "
                f"terminal and parent had never executed."
            ),
        )
        topmost_cancelled = parent
        cursor = parent
    # Loop exhausted MAX_DEPTH. Look one step above the last cancelled
    # parent: if there's still a qualifying ancestor we couldn't reach,
    # the cascade was genuinely truncated; record the audit. If not,
    # the chain was exactly MAX_DEPTH long and we processed it fully —
    # no truncation, no audit.
    next_qualifier = await _qualifying_umbrella_parent(session, task=cursor)
    if next_qualifier is not None:
        logger.warning(
            "umbrella cascade truncated at MAX_DEPTH=%d (last cancelled task=%s); "
            "check parent_task_id chain for unexpected depth or cycles",
            _UMBRELLA_CASCADE_MAX_DEPTH, cursor.id,
        )
        record_activity(
            session,
            event_type="task.umbrella_cascade_truncated",
            task_id=cursor.id,
            board_id=cursor.board_id,
            message=(
                f"Cascade depth cap ({_UMBRELLA_CASCADE_MAX_DEPTH}) reached "
                f"during umbrella auto-cancel walk; check parent_task_id "
                f"chain for unexpected depth or cycles."
            ),
        )
    return topmost_cancelled


async def _qualifying_umbrella_parent(
    session: AsyncSession,
    *,
    task: Task,
) -> Task | None:
    """Return the parent of ``task`` if it qualifies as a retired umbrella
    ready for auto-cancel — else None. All cheap checks first, then the
    DB hits, then the marker query (most expensive)."""
    parent_id = task.parent_task_id
    if parent_id is None:
        return None

    parent = (
        await session.exec(select(Task).where(col(Task.id) == parent_id))
    ).first()
    if parent is None:
        return None
    if parent.status != "inbox":
        return None
    if parent.in_progress_at is not None or parent.previous_in_progress_at is not None:
        return None

    siblings = list(
        await session.exec(select(Task).where(col(Task.parent_task_id) == parent_id)),
    )
    if not siblings:
        return None
    if any(sib.status not in TERMINAL_STATUSES for sib in siblings):
        return None

    # The lead-posted UMBRELLA_RETIRED marker is the explicit "this
    # parent is decomposition-completed and its work shipped via
    # children" signal. The never-executed heuristic alone is too broad.
    if parent.board_id is not None:
        retired_ids = await task_ids_with_umbrella_retired_marker(
            session, board_id=parent.board_id, task_ids=[parent.id],
        )
        if parent.id not in retired_ids:
            return None

    return parent


async def maybe_cascade_umbrella_close_by_id(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> Task | None:
    """Convenience wrapper for paths that only carry the task id."""
    task = (
        await session.exec(select(Task).where(col(Task.id) == task_id))
    ).first()
    if task is None:
        return None
    return await maybe_cascade_umbrella_close(session, task=task)


async def orphan_children_with_terminal_parent(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> dict[UUID, UUID]:
    """Return ``{child_id: parent_id}`` for orphans across the board.

    Selects every non-terminal task whose ``parent_task_id`` references
    a terminal parent on the same board. Used by the lead-next-action
    gate to surface ``cancel_orphan_child`` candidates without
    walking each task's parent in a separate query.
    """
    parent_alias = Task.__table__.alias("parent")  # pyright: ignore[reportAttributeAccessIssue]
    child = Task.__table__  # pyright: ignore[reportAttributeAccessIssue]
    stmt = (
        select(child.c.id, child.c.parent_task_id)
        .select_from(
            child.join(parent_alias, child.c.parent_task_id == parent_alias.c.id),
        )
        .where(child.c.board_id == board_id)
        .where(child.c.status.not_in(TERMINAL_STATUSES))
        .where(parent_alias.c.status.in_(TERMINAL_STATUSES))
        .where(parent_alias.c.board_id == board_id)
        .order_by(child.c.created_at.asc())
    )
    return {child_id: parent_id for child_id, parent_id in (await session.exec(stmt)).all()}
