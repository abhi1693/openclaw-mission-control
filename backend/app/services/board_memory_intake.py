"""Deterministic intake for operator findings stored in board memory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.time import utcnow
from app.models.board_memory import BoardMemory
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

URL_RE = re.compile(r"https?://[^\s<>)\"']+")
TITLE_MAX_LENGTH = 120


@dataclass(frozen=True)
class BoardMemoryIntakeResult:
    """Summary of one reconciliation pass."""

    scanned: int = 0
    created: int = 0
    skipped_existing: int = 0
    skipped_non_actionable: int = 0


def _normalized_tags(memory: BoardMemory) -> set[str]:
    return {str(tag).strip().lower() for tag in (memory.tags or []) if str(tag).strip()}


def is_actionable_operator_memory(memory: BoardMemory) -> bool:
    """Return true when memory should deterministically create an intake task."""

    tags = _normalized_tags(memory)
    if "e2e_canary" in tags:
        return False
    if "operator" not in tags:
        return False
    return "findings" in tags or "marketing_site_review" in tags


def _title_from_content(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:TITLE_MAX_LENGTH]
    return "Operator findings intake"


def _first_url(content: str) -> str | None:
    match = URL_RE.search(content)
    if match is None:
        return None
    return match.group(0).rstrip(".,;:")


async def reconcile_board_memory_intake(
    session: "AsyncSession",
    *,
    board_id: UUID,
    lookback_days: int = 7,
) -> BoardMemoryIntakeResult:
    """Create missing inbox tasks for recent actionable operator memory."""

    since = utcnow() - timedelta(days=lookback_days)
    memories = (
        await session.exec(
            select(BoardMemory)
            .where(col(BoardMemory.board_id) == board_id)
            .where(col(BoardMemory.created_at) >= since)
            .order_by(col(BoardMemory.created_at)),
        )
    ).all()
    scanned = len(memories)
    created = 0
    skipped_existing = 0
    skipped_non_actionable = 0

    for memory in memories:
        if not is_actionable_operator_memory(memory):
            skipped_non_actionable += 1
            continue
        legacy_marker = f"source_memory_id={memory.id}"
        existing = (
            await session.exec(
                select(Task.id).where(
                    (col(Task.source_memory_id) == memory.id)
                    | col(Task.description).contains(legacy_marker),
                ),
            )
        ).first()
        if existing is not None:
            skipped_existing += 1
            continue

        url = _first_url(memory.content)
        task = Task(
            board_id=board_id,
            title=_title_from_content(memory.content),
            description=memory.content,
            status="inbox",
            priority="high",
            source_memory_id=memory.id,
            auto_created=True,
            auto_reason="board_memory_intake",
        )
        if url:
            task.review_packet_type = "frontend_ui"
            task.validation_target = url
            task.validation_target_kind = "live_url"
            task.validation_target_scope = "review"
        try:
            async with session.begin_nested():
                session.add(task)
                await session.flush()
        except IntegrityError:
            skipped_existing += 1
            continue
        created += 1

    await session.commit()
    return BoardMemoryIntakeResult(
        scanned=scanned,
        created=created,
        skipped_existing=skipped_existing,
        skipped_non_actionable=skipped_non_actionable,
    )
