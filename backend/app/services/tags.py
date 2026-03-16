"""Helpers for validating and loading tags and tag mappings."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func
from sqlmodel import col, select

from app.models.tag_assignments import TagAssignment
from app.models.tags import Tag
from app.schemas.tags import TagRef

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_tag(value: str) -> str:
    """Build a slug from arbitrary text using lowercase alphanumeric groups."""
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "tag"


def _dedupe_uuid_list(values: Sequence[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


async def validate_tag_ids(
    session: AsyncSession,
    *,
    organization_id: UUID,
    tag_ids: Sequence[UUID],
) -> list[UUID]:
    """Validate tag IDs within an organization and return deduped IDs."""
    normalized = _dedupe_uuid_list(tag_ids)
    if not normalized:
        return []

    existing_ids = set(
        await session.exec(
            select(Tag.id)
            .where(col(Tag.organization_id) == organization_id)
            .where(col(Tag.id).in_(normalized)),
        ),
    )
    missing = [tag_id for tag_id in normalized if tag_id not in existing_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "One or more tags do not exist in this organization.",
                "missing_tag_ids": [str(tag_id) for tag_id in missing],
            },
        )
    return normalized


@dataclass(slots=True)
class TagState:
    """Ordered tag state for a task payload."""

    tag_ids: list[UUID] = field(default_factory=list)
    tags: list[TagRef] = field(default_factory=list)


async def load_tag_state(
    session: AsyncSession,
    *,
    task_ids: Sequence[UUID],
) -> dict[UUID, TagState]:
    """Return ordered tag IDs and refs for each task id."""
    normalized_task_ids = _dedupe_uuid_list(task_ids)
    if not normalized_task_ids:
        return {}

    rows = list(
        await session.exec(
            select(
                col(TagAssignment.task_id),
                Tag,
            )
            .join(Tag, col(Tag.id) == col(TagAssignment.tag_id))
            .where(col(TagAssignment.task_id).in_(normalized_task_ids))
            .order_by(
                col(TagAssignment.task_id).asc(),
                col(TagAssignment.created_at).asc(),
            ),
        ),
    )
    state_by_task_id: dict[UUID, TagState] = defaultdict(TagState)
    for task_id, tag in rows:
        if task_id is None:
            continue
        state = state_by_task_id[task_id]
        state.tag_ids.append(tag.id)
        state.tags.append(
            TagRef(
                id=tag.id,
                name=tag.name,
                slug=tag.slug,
                color=tag.color,
            ),
        )
    return dict(state_by_task_id)


async def replace_tags(
    session: AsyncSession,
    *,
    task_id: UUID,
    tag_ids: Sequence[UUID],
) -> None:
    """Replace all tag-assignment rows for a task."""
    normalized = _dedupe_uuid_list(tag_ids)
    await session.exec(
        delete(TagAssignment).where(
            col(TagAssignment.task_id) == task_id,
        ),
    )
    for tag_id in normalized:
        session.add(TagAssignment(task_id=task_id, tag_id=tag_id))


async def task_counts_for_tags(
    session: AsyncSession,
    *,
    tag_ids: Sequence[UUID],
) -> dict[UUID, int]:
    """Return count of tagged tasks per tag id."""
    normalized = _dedupe_uuid_list(tag_ids)
    if not normalized:
        return {}
    rows = list(
        await session.exec(
            select(
                col(TagAssignment.tag_id),
                func.count(col(TagAssignment.task_id)),
            )
            .where(col(TagAssignment.tag_id).in_(normalized))
            .group_by(col(TagAssignment.tag_id)),
        ),
    )
    return {tag_id: int(count or 0) for tag_id, count in rows}
