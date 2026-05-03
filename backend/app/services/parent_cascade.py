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

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.tasks import Task
from app.services.activity_log import record_activity

TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})


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
    """
    from app.models.activity_events import ActivityEvent  # local — avoid circular

    task_id_list = list(task_ids)
    if not task_id_list:
        return frozenset()
    stmt = (
        select(col(ActivityEvent.task_id))
        .where(col(ActivityEvent.board_id) == board_id)
        .where(col(ActivityEvent.task_id).in_(task_id_list))
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.message).is_not(None))
        .where(col(ActivityEvent.message).contains("UMBRELLA_RETIRED"))
        .distinct()
    )
    return frozenset(
        task_id for task_id in (await session.exec(stmt)).all()
        if task_id is not None
    )


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

    Fires from ``_finalize_updated_task`` after a status transition into
    ``TERMINAL_STATUSES``. Walks up the parent chain: if grandparent is
    also a retired umbrella whose only remaining child was the parent
    we just cancelled, cascade again. Returns the topmost parent that
    was cancelled, or None if no cascade fired.

    **Why ``cancelled`` (not ``done``):** the umbrella never executed,
    its work shipped via children. ``done`` claims completion of
    work-on-this-row (false); ``cancelled`` says "no longer needs to
    happen here" (true).

    **Safety net** — the cascade only fires when
    ``parent.in_progress_at IS NULL AND parent.previous_in_progress_at IS NULL``.
    A parent with execution history may be a regular task that intends to
    do work after its children; auto-cancelling it would silently delete
    operator-attributed work.

    Caller must ``session.commit()`` if the result is non-None.
    """
    if task.status not in TERMINAL_STATUSES:
        return None
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

    parent.status = "cancelled"
    parent.cancelled_at = utcnow()
    parent.updated_at = parent.cancelled_at
    session.add(parent)
    # Audit row so dashboards / debug queries / lead-next-action can
    # see the auto-cancel and don't mistake the parent for an unexplained
    # operator decision. board_id may be None for legacy rows; record
    # whatever is on the parent.
    record_activity(
        session,
        event_type="task.umbrella_auto_cascaded",
        task_id=parent.id,
        board_id=parent.board_id,
        message=(
            f"Parent auto-cancelled by umbrella cascade after child "
            f"{task.id} reached status={task.status}; all siblings terminal "
            f"and parent had never executed."
        ),
    )

    # Recurse: if grandparent is also a retired umbrella whose only
    # non-terminal child was this parent, cancel it too. Without this,
    # multi-level decomposition chains leak.
    grandparent = await maybe_cascade_umbrella_close(session, task=parent)
    return grandparent if grandparent is not None else parent


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
