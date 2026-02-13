"""Helpers for normalizing and querying approval-task associations."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, delete, exists, func
from sqlmodel import col, select

from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

TASK_ID_KEYS: tuple[str, ...] = ("task_id", "taskId", "taskID")
TASK_IDS_KEYS: tuple[str, ...] = ("task_ids", "taskIds", "taskIDs")


def _coerce_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def extract_task_ids(payload: dict[str, object] | None) -> list[UUID]:
    """Extract task UUIDs from approval payload aliases."""
    if not payload:
        return []

    collected: list[UUID] = []
    for key in TASK_IDS_KEYS:
        raw = payload.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            for item in raw:
                task_id = _coerce_uuid(item)
                if task_id is not None:
                    collected.append(task_id)
    for key in TASK_ID_KEYS:
        task_id = _coerce_uuid(payload.get(key))
        if task_id is not None:
            collected.append(task_id)

    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for task_id in collected:
        if task_id in seen:
            continue
        seen.add(task_id)
        deduped.append(task_id)
    return deduped


def normalize_task_ids(
    *,
    task_id: UUID | None,
    task_ids: Sequence[UUID],
    payload: dict[str, object] | None,
) -> list[UUID]:
    """Merge explicit and payload-provided task references into an ordered unique list."""
    merged: list[UUID] = []
    merged.extend(task_ids)
    if task_id is not None:
        merged.append(task_id)
    merged.extend(extract_task_ids(payload))

    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in merged:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


async def load_task_ids_by_approval(
    session: AsyncSession,
    *,
    approval_ids: Iterable[UUID],
) -> dict[UUID, list[UUID]]:
    """Return task ids grouped by approval id in insertion order."""
    ids = list({*approval_ids})
    if not ids:
        return {}

    rows = list(
        await session.exec(
            select(col(ApprovalTaskLink.approval_id), col(ApprovalTaskLink.task_id))
            .where(col(ApprovalTaskLink.approval_id).in_(ids))
            .order_by(col(ApprovalTaskLink.created_at).asc()),
        ),
    )

    mapping: dict[UUID, list[UUID]] = {approval_id: [] for approval_id in ids}
    for approval_id, task_id in rows:
        mapping.setdefault(approval_id, []).append(task_id)
    return mapping


async def replace_approval_task_links(
    session: AsyncSession,
    *,
    approval_id: UUID,
    task_ids: Sequence[UUID],
) -> None:
    """Replace approval-task link rows for an approval id."""
    await session.exec(
        delete(ApprovalTaskLink).where(
            col(ApprovalTaskLink.approval_id) == approval_id,
        ),
    )
    for task_id in task_ids:
        session.add(ApprovalTaskLink(approval_id=approval_id, task_id=task_id))


async def lock_tasks_for_approval(
    session: AsyncSession,
    *,
    task_ids: Sequence[UUID],
) -> None:
    """Acquire row locks for task ids in deterministic order within a transaction."""
    normalized_task_ids = sorted({*task_ids}, key=str)
    if not normalized_task_ids:
        return
    statement = (
        select(col(Task.id))
        .where(col(Task.id).in_(normalized_task_ids))
        .order_by(col(Task.id).asc())
        .with_for_update()
    )
    # Materialize results so the lock query fully executes before proceeding.
    _ = list(await session.exec(statement))


async def pending_approval_conflicts_by_task(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Sequence[UUID],
    exclude_approval_id: UUID | None = None,
) -> dict[UUID, UUID]:
    """Return the first conflicting pending approval id for each requested task id."""
    normalized_task_ids = list({*task_ids})
    if not normalized_task_ids:
        return {}

    linked_statement = (
        select(
            col(ApprovalTaskLink.task_id),
            col(Approval.id),
            col(Approval.created_at),
        )
        .join(Approval, col(Approval.id) == col(ApprovalTaskLink.approval_id))
        .where(col(Approval.board_id) == board_id)
        .where(col(Approval.status) == "pending")
        .where(col(ApprovalTaskLink.task_id).in_(normalized_task_ids))
        .order_by(col(Approval.created_at).asc(), col(Approval.id).asc())
    )
    if exclude_approval_id is not None:
        linked_statement = linked_statement.where(col(Approval.id) != exclude_approval_id)
    linked_rows = list(await session.exec(linked_statement))

    conflicts: dict[UUID, UUID] = {}
    for task_id, approval_id, _created_at in linked_rows:
        conflicts.setdefault(task_id, approval_id)

    legacy_statement = (
        select(
            col(Approval.task_id),
            col(Approval.id),
            col(Approval.created_at),
        )
        .where(col(Approval.board_id) == board_id)
        .where(col(Approval.status) == "pending")
        .where(col(Approval.task_id).is_not(None))
        .where(col(Approval.task_id).in_(normalized_task_ids))
        .where(
            ~exists(
                select(1)
                .where(col(ApprovalTaskLink.approval_id) == col(Approval.id))
                .correlate(Approval),
            ),
        )
        .order_by(col(Approval.created_at).asc(), col(Approval.id).asc())
    )
    if exclude_approval_id is not None:
        legacy_statement = legacy_statement.where(col(Approval.id) != exclude_approval_id)
    legacy_rows = list(await session.exec(legacy_statement))

    for legacy_task_id_opt, approval_id, _created_at in legacy_rows:
        if legacy_task_id_opt is None:
            continue
        # mypy: SQL rows can include NULL task_id; guard before using as dict[UUID, UUID] key.
        conflicts.setdefault(legacy_task_id_opt, approval_id)

    return conflicts


async def task_counts_for_board(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: set[UUID] | None = None,
) -> dict[UUID, tuple[int, int]]:
    """Compute total/pending approval counts per task across all linked tasks on a board."""

    link_statement = (
        select(
            col(ApprovalTaskLink.task_id),
            func.count(col(Approval.id)).label("total"),
            func.sum(
                case(
                    (col(Approval.status) == "pending", 1),
                    else_=0,
                ),
            ).label("pending"),
        )
        .join(Approval, col(Approval.id) == col(ApprovalTaskLink.approval_id))
        .where(col(Approval.board_id) == board_id)
    )
    if task_ids is not None:
        if not task_ids:
            return {}
        link_statement = link_statement.where(col(ApprovalTaskLink.task_id).in_(task_ids))
    link_statement = link_statement.group_by(col(ApprovalTaskLink.task_id))

    counts: dict[UUID, tuple[int, int]] = {}
    for task_id, total, pending in list(await session.exec(link_statement)):
        counts[task_id] = (int(total or 0), int(pending or 0))

    # Backward compatibility: include legacy rows that have task_id set but no link rows.
    legacy_statement = (
        select(
            col(Approval.task_id),
            func.count(col(Approval.id)).label("total"),
            func.sum(
                case(
                    (col(Approval.status) == "pending", 1),
                    else_=0,
                ),
            ).label("pending"),
        )
        .where(col(Approval.board_id) == board_id)
        .where(col(Approval.task_id).is_not(None))
        .where(
            ~exists(
                select(1)
                .where(col(ApprovalTaskLink.approval_id) == col(Approval.id))
                .correlate(Approval),
            ),
        )
    )
    if task_ids is not None:
        legacy_statement = legacy_statement.where(col(Approval.task_id).in_(task_ids))
    legacy_statement = legacy_statement.group_by(col(Approval.task_id))

    for legacy_task_id, total, pending in list(await session.exec(legacy_statement)):
        if legacy_task_id is None:
            continue
        previous = counts.get(legacy_task_id, (0, 0))
        counts[legacy_task_id] = (
            previous[0] + int(total or 0),
            previous[1] + int(pending or 0),
        )
    return counts
