"""Parent-child cascade helpers for the Phase V decomposition link.

When a parent task reaches a terminal state (``done``/``cancelled``),
its non-terminal children become *orphans* — work items whose
reason-for-being just evaporated. Without explicit propagation, those
children outlive the parent and accumulate as background friction
(see the 2026-05-01 ``Hero accent → Deploy artifact parity`` case).

This module provides batch + scalar lookups so the read-side response
can surface ``orphan_child_task_ids`` and the lead-next-action gate
can route cleanup actions. The module deliberately does NOT mutate
state — propagation happens in the API layer (activity events,
optional lead-cancel narrow exception in a follow-up PR) so the
audit trail stays explicit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tasks import Task

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
