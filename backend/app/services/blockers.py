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
from app.services.blocker_reason_codes import group_codes_by_task


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
