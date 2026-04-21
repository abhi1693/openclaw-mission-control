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
from uuid import UUID

from sqlalchemy import exists
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blockers import Blocker


async def task_ids_with_open_blocker(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Iterable[UUID],
) -> set[UUID]:
    """Return the subset of the given task ids that have any open blocker.

    "Open" means ``resolved_at IS NULL``. The board_id filter keeps
    the query tenant-scoped and lets the partial
    ``ix_blockers_board_id_open`` index do the work on Postgres.
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
