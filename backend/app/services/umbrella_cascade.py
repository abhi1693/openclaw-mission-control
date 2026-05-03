"""Umbrella auto-cascade: retire never-executed parents when children terminate.

Repro 2026-05-03: ``a8a67bc8`` (Phase 2.5 Stats + trust-line truth packet)
was decomposed by Architect into 5 child tasks (AC1-AC5) and explicitly
retired with the in-thread marker ``UMBRELLA_RETIRED``. When the last
child (AC5) reached ``done``, the dep-derivation correctly recomputed
``is_blocked=False`` on the parent — but the parent stayed in ``inbox``
forever, polluting the queue and confusing the lead next-action gate.

The fix: when a task transitions to a terminal status (``done`` or
``cancelled``) and it has a ``parent_task_id``, check whether the
parent qualifies as a never-executed coordination landmark whose
children are now all terminal. If yes, auto-cancel the parent.

**Why ``cancelled`` (not ``done``):** the umbrella never ran. ``done``
implies completion of work-on-this-row, which is false. ``cancelled``
captures "no longer needs to happen here — work shipped via children."

**Safety net:** the cascade only fires when
``parent.in_progress_at IS NULL AND parent.previous_in_progress_at IS NULL``.
That clause prevents false positives where a regular parent task with
subtasks (one that DID intend to do work after children) gets
auto-cancelled before it ran. A truly retired umbrella never had an
execution cycle, so both timestamps are null.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.tasks import Task

# Statuses that a sibling can be in to count as "terminal" for the
# parent's cascade decision. Same set used by task_dependencies for
# dep satisfaction (kept local rather than imported to avoid a cyclic
# import — these are by definition the terminal lifecycle states).
_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "cancelled"})


async def maybe_cascade_umbrella_close(
    session: AsyncSession,
    *,
    task: Task,
) -> Task | None:
    """If this task's terminal status closes a retired-umbrella parent,
    auto-cancel the parent and return it. Returns None when no cascade
    fires.

    Caller is responsible for ``session.commit()`` afterwards if the
    result is non-None — keeping commit out of this helper lets callers
    batch with their own transaction work, mirroring the pattern in
    ``auto_resolve_pipeline_blockers_if_ready``.
    """
    if task.status not in _TERMINAL_STATUSES:
        return None
    parent_id = task.parent_task_id
    if parent_id is None:
        return None

    parent = (
        await session.exec(select(Task).where(col(Task.id) == parent_id))
    ).first()
    if parent is None:
        return None
    # Only retire parents that are still in inbox (not in_progress, not
    # review, not rework, not already terminal). A parent that's in
    # in_progress means an agent is actively working it; cascading it
    # to cancelled would silently delete in-flight work.
    if parent.status != "inbox":
        return None
    # The "never-executed" safety net. A true coordination umbrella
    # has no execution cycle on its own row — both timestamps are null.
    # If either is set, the parent had real work attached at some point
    # and an operator should make the close decision explicitly.
    if parent.in_progress_at is not None or parent.previous_in_progress_at is not None:
        return None

    siblings = list(
        await session.exec(select(Task).where(col(Task.parent_task_id) == parent_id)),
    )
    if not siblings:
        return None
    if any(sib.status not in _TERMINAL_STATUSES for sib in siblings):
        return None

    parent.status = "cancelled"
    parent.cancelled_at = utcnow()
    parent.updated_at = parent.cancelled_at
    session.add(parent)
    return parent


async def maybe_cascade_umbrella_close_by_id(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> Task | None:
    """Convenience wrapper when only the task id is in scope (e.g. in
    notification paths that don't carry the ORM row)."""
    task = (
        await session.exec(select(Task).where(col(Task.id) == task_id))
    ).first()
    if task is None:
        return None
    return await maybe_cascade_umbrella_close(session, task=task)
