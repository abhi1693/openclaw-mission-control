"""Sprint retrospective entry CRUD and stats endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.retro_entries import RetroEntry
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.retro_entries import (
    RetroEntryCreate,
    RetroEntryRead,
    RetroEntryUpdate,
    RetroStatItem,
)

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/retros", tags=["retros"])

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)

# Keep RUNTIME_ANNOTATION_TYPES so deferred annotations resolve correctly.
_RUNTIME_TYPE_REFERENCES = (UUID, datetime)


# --------------------------------------------------------------------------- #
#  Stats (must be registered BEFORE /{id} to avoid path parameter collision)  #
# --------------------------------------------------------------------------- #


@router.get(
    "/stats",
    response_model=list[RetroStatItem],
    summary="Retro Stats",
    description="Return per-sprint per-category entry counts for this board.",
)
async def get_retro_stats(
    *,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> list[RetroStatItem]:
    """Aggregate retro entries by sprint_id and category."""
    stmt = (
        select(
            col(RetroEntry.sprint_id),
            col(RetroEntry.category),
            func.count(RetroEntry.id).label("count"),
        )
        .where(col(RetroEntry.board_id) == board.id)
        .group_by(col(RetroEntry.sprint_id), col(RetroEntry.category))
        .order_by(col(RetroEntry.sprint_id), col(RetroEntry.category))
    )
    result = await session.exec(stmt)  # type: ignore[call-overload]
    rows = result.all()
    return [
        RetroStatItem(sprint_id=row.sprint_id, category=row.category, count=row.count)
        for row in rows
    ]


# --------------------------------------------------------------------------- #
#  CRUD                                                                        #
# --------------------------------------------------------------------------- #


@router.post("", response_model=RetroEntryRead, status_code=status.HTTP_201_CREATED)
async def create_retro_entry(
    payload: RetroEntryCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> RetroEntry:
    """Create a new sprint retrospective entry."""
    entry = RetroEntry(
        board_id=board.id,
        **payload.model_dump(),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.get("", response_model=DefaultLimitOffsetPage[RetroEntryRead])
async def list_retro_entries(
    *,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
    sprint_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    author: str | None = Query(default=None),
    retro_status: str | None = Query(default=None, alias="status"),
) -> LimitOffsetPage[RetroEntryRead]:
    """List retro entries with optional filters."""
    statement = RetroEntry.objects.filter_by(board_id=board.id)
    if sprint_id is not None:
        statement = statement.filter(col(RetroEntry.sprint_id) == sprint_id)
    if category is not None:
        statement = statement.filter(col(RetroEntry.category) == category)
    if author is not None:
        statement = statement.filter(col(RetroEntry.author) == author)
    if retro_status is not None:
        statement = statement.filter(col(RetroEntry.status) == retro_status)
    statement = statement.order_by(col(RetroEntry.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/{retro_id}", response_model=RetroEntryRead)
async def get_retro_entry(
    retro_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> RetroEntry:
    """Get a single retro entry by id."""
    entry = await RetroEntry.objects.by_id(retro_id).first(session)
    if entry is None or entry.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return entry


@router.patch("/{retro_id}", response_model=RetroEntryRead)
async def update_retro_entry(
    retro_id: UUID,
    payload: RetroEntryUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> RetroEntry:
    """Partially update a retro entry."""
    entry = await RetroEntry.objects.by_id(retro_id).first(session)
    if entry is None or entry.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = utcnow()
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/{retro_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_retro_entry(
    retro_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> None:
    """Delete a retro entry."""
    entry = await RetroEntry.objects.by_id(retro_id).first(session)
    if entry is None or entry.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await session.delete(entry)
    await session.commit()
