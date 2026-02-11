"""Activity listing and task-comment feed endpoints."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, desc, func
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, require_admin_or_agent, require_org_member
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.activity_events import ActivityEventRead, ActivityTaskCommentFeedItemRead
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.organizations import (
    OrganizationContext,
    get_active_membership,
    list_accessible_board_ids,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/activity", tags=["activity"])

SSE_SEEN_MAX = 2000
STREAM_POLL_SECONDS = 2
TASK_COMMENT_ROW_LEN = 4
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_admin_or_agent)
ORG_MEMBER_DEP = Depends(require_org_member)
BOARD_ID_QUERY = Query(default=None)
SINCE_QUERY = Query(default=None)
_RUNTIME_TYPE_REFERENCES = (UUID,)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _agent_role(agent: Agent | None) -> str | None:
    if agent is None:
        return None
    profile = agent.identity_profile
    if not isinstance(profile, dict):
        return None
    raw = profile.get("role")
    if isinstance(raw, str):
        role = raw.strip()
        return role or None
    return None


def _feed_item(
    event: ActivityEvent,
    task: Task,
    board: Board,
    agent: Agent | None,
) -> ActivityTaskCommentFeedItemRead:
    return ActivityTaskCommentFeedItemRead(
        id=event.id,
        created_at=event.created_at,
        message=event.message,
        agent_id=event.agent_id,
        agent_name=agent.name if agent else None,
        agent_role=_agent_role(agent),
        task_id=task.id,
        task_title=task.title,
        board_id=board.id,
        board_name=board.name,
    )


def _coerce_task_comment_rows(
    items: Sequence[Any],
) -> list[tuple[ActivityEvent, Task, Board, Agent | None]]:
    rows: list[tuple[ActivityEvent, Task, Board, Agent | None]] = []
    for item in items:
        first: Any
        second: Any
        third: Any
        fourth: Any

        if isinstance(item, tuple):
            if len(item) != TASK_COMMENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task, Board, Agent | None) rows"
                raise TypeError(msg)
            first, second, third, fourth = item
        else:
            try:
                row_len = len(item)
                first = item[0]
                second = item[1]
                third = item[2]
                fourth = item[3]
            except (IndexError, KeyError, TypeError):
                msg = "Expected (ActivityEvent, Task, Board, Agent | None) rows"
                raise TypeError(msg) from None
            if row_len != TASK_COMMENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task, Board, Agent | None) rows"
                raise TypeError(msg)

        if (
            isinstance(first, ActivityEvent)
            and isinstance(second, Task)
            and isinstance(third, Board)
            and (isinstance(fourth, Agent) or fourth is None)
        ):
            rows.append((first, second, third, fourth))
            continue

        msg = "Expected (ActivityEvent, Task, Board, Agent | None) rows"
        raise TypeError(msg)
    return rows


async def _fetch_task_comment_events(
    session: AsyncSession,
    since: datetime,
    *,
    board_id: UUID | None = None,
) -> Sequence[tuple[ActivityEvent, Task, Board, Agent | None]]:
    statement = (
        select(ActivityEvent, Task, Board, Agent)
        .join(Task, col(ActivityEvent.task_id) == col(Task.id))
        .join(Board, col(Task.board_id) == col(Board.id))
        .outerjoin(Agent, col(ActivityEvent.agent_id) == col(Agent.id))
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.created_at) >= since)
        .where(func.length(func.trim(col(ActivityEvent.message))) > 0)
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    if board_id is not None:
        statement = statement.where(col(Task.board_id) == board_id)
    return _coerce_task_comment_rows(list(await session.exec(statement)))


@router.get("", response_model=DefaultLimitOffsetPage[ActivityEventRead])
async def list_activity(
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> LimitOffsetPage[ActivityEventRead]:
    """List activity events visible to the calling actor."""
    statement = select(ActivityEvent)
    if actor.actor_type == "agent" and actor.agent:
        statement = statement.where(ActivityEvent.agent_id == actor.agent.id)
    elif actor.actor_type == "user" and actor.user:
        member = await get_active_membership(session, actor.user)
        if member is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        board_ids = await list_accessible_board_ids(session, member=member, write=False)
        if not board_ids:
            statement = statement.where(col(ActivityEvent.id).is_(None))
        else:
            statement = statement.join(
                Task,
                col(ActivityEvent.task_id) == col(Task.id),
            ).where(col(Task.board_id).in_(board_ids))
    statement = statement.order_by(desc(col(ActivityEvent.created_at)))
    return await paginate(session, statement)


@router.get(
    "/task-comments",
    response_model=DefaultLimitOffsetPage[ActivityTaskCommentFeedItemRead],
)
async def list_task_comment_feed(
    board_id: UUID | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> LimitOffsetPage[ActivityTaskCommentFeedItemRead]:
    """List task-comment feed items for accessible boards."""
    statement = (
        select(ActivityEvent, Task, Board, Agent)
        .join(Task, col(ActivityEvent.task_id) == col(Task.id))
        .join(Board, col(Task.board_id) == col(Board.id))
        .outerjoin(Agent, col(ActivityEvent.agent_id) == col(Agent.id))
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(func.length(func.trim(col(ActivityEvent.message))) > 0)
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    board_ids = await list_accessible_board_ids(session, member=ctx.member, write=False)
    if board_id is not None:
        if board_id not in set(board_ids):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        statement = statement.where(col(Task.board_id) == board_id)
    elif board_ids:
        statement = statement.where(col(Task.board_id).in_(board_ids))
    else:
        statement = statement.where(col(Task.id).is_(None))

    def _transform(items: Sequence[Any]) -> Sequence[Any]:
        rows = _coerce_task_comment_rows(items)
        return [_feed_item(event, task, board, agent) for event, task, board, agent in rows]

    return await paginate(session, statement, transformer=_transform)


@router.get("/task-comments/stream")
async def stream_task_comment_feed(
    request: Request,
    board_id: UUID | None = BOARD_ID_QUERY,
    since: str | None = SINCE_QUERY,
    db_session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> EventSourceResponse:
    """Stream task-comment events for accessible boards."""
    since_dt = _parse_since(since) or utcnow()
    board_ids = await list_accessible_board_ids(
        db_session,
        member=ctx.member,
        write=False,
    )
    allowed_ids = set(board_ids)
    if board_id is not None and board_id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    seen_ids: set[UUID] = set()
    seen_queue: deque[UUID] = deque()

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        last_seen = since_dt
        while True:
            if await request.is_disconnected():
                break
            async with async_session_maker() as stream_session:
                if board_id is not None:
                    rows = await _fetch_task_comment_events(
                        stream_session,
                        last_seen,
                        board_id=board_id,
                    )
                elif allowed_ids:
                    rows = await _fetch_task_comment_events(stream_session, last_seen)
                    rows = [row for row in rows if row[1].board_id in allowed_ids]
                else:
                    rows = []
            for event, task, board, agent in rows:
                event_id = event.id
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                seen_queue.append(event_id)
                if len(seen_queue) > SSE_SEEN_MAX:
                    oldest = seen_queue.popleft()
                    seen_ids.discard(oldest)
                last_seen = max(event.created_at, last_seen)
                payload = {
                    "comment": _feed_item(
                        event,
                        task,
                        board,
                        agent,
                    ).model_dump(mode="json"),
                }
                yield {"event": "comment", "data": json.dumps(payload)}
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(event_generator(), ping=15)
