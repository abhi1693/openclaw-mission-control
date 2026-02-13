"""Board-group memory CRUD and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlmodel import col
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_admin_or_agent,
    require_org_member,
)
from app.core.config import settings
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.agents import Agent
from app.models.board_group_memory import BoardGroupMemory
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.models.users import User
from app.schemas.board_group_memory import BoardGroupMemoryCreate, BoardGroupMemoryRead
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.mentions import extract_mentions, matches_agent_mention
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.organizations import (
    is_org_admin,
    list_accessible_board_ids,
    member_all_boards_read,
    member_all_boards_write,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

router = APIRouter(tags=["board-group-memory"])
group_router = APIRouter(
    prefix="/board-groups/{group_id}/memory",
    tags=["board-group-memory"],
)
board_router = APIRouter(
    prefix="/boards/{board_id}/group-memory",
    tags=["board-group-memory"],
)
MAX_SNIPPET_LENGTH = 800
STREAM_POLL_SECONDS = 2
SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
ACTOR_DEP = Depends(require_admin_or_agent)
IS_CHAT_QUERY = Query(default=None)
SINCE_QUERY = Query(default=None)
_RUNTIME_TYPE_REFERENCES = (UUID,)
AGENT_BOARD_ROLE_TAGS = cast("list[str | Enum]", ["agent-lead", "agent-worker"])


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


def _serialize_memory(memory: BoardGroupMemory) -> dict[str, object]:
    return BoardGroupMemoryRead.model_validate(
        memory,
        from_attributes=True,
    ).model_dump(mode="json")


async def _fetch_memory_events(
    session: AsyncSession,
    board_group_id: UUID,
    since: datetime,
    is_chat: bool | None = None,
) -> list[BoardGroupMemory]:
    statement = (
        BoardGroupMemory.objects.filter_by(board_group_id=board_group_id)
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardGroupMemory.content))) > 0)
    )
    if is_chat is not None:
        statement = statement.filter(col(BoardGroupMemory.is_chat) == is_chat)
    statement = statement.filter(col(BoardGroupMemory.created_at) >= since).order_by(
        col(BoardGroupMemory.created_at),
    )
    return await statement.all(session)


async def _require_group_access(
    session: AsyncSession,
    *,
    group_id: UUID,
    ctx: OrganizationContext,
    write: bool,
) -> BoardGroup:
    group = await BoardGroup.objects.by_id(group_id).first(session)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if group.organization_id != ctx.member.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if write and member_all_boards_write(ctx.member):
        return group
    if not write and member_all_boards_read(ctx.member):
        return group

    board_ids = [
        board.id
        for board in await Board.objects.filter_by(board_group_id=group_id).all(
            session,
        )
    ]
    if not board_ids:
        if is_org_admin(ctx.member):
            return group
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    allowed_ids = await list_accessible_board_ids(
        session,
        member=ctx.member,
        write=write,
    )
    if not set(board_ids).intersection(set(allowed_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return group


async def _group_read_access(
    group_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> BoardGroup:
    return await _require_group_access(session, group_id=group_id, ctx=ctx, write=False)


GROUP_READ_DEP = Depends(_group_read_access)


def _group_chat_targets(
    *,
    agents: list[Agent],
    actor: ActorContext,
    is_broadcast: bool,
    mentions: set[str],
) -> dict[str, Agent]:
    targets: dict[str, Agent] = {}
    for agent in agents:
        if not agent.openclaw_session_id:
            continue
        if actor.actor_type == "agent" and actor.agent and agent.id == actor.agent.id:
            continue
        if is_broadcast or agent.is_board_lead:
            targets[str(agent.id)] = agent
            continue
        if mentions and matches_agent_mention(agent, mentions):
            targets[str(agent.id)] = agent
    return targets


def _group_actor_name(actor: ActorContext) -> str:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.name
    if actor.user:
        return actor.user.preferred_name or actor.user.name or "User"
    return "User"


def _group_header(*, is_broadcast: bool, mentioned: bool) -> str:
    if is_broadcast:
        return "GROUP BROADCAST"
    if mentioned:
        return "GROUP CHAT MENTION"
    return "GROUP CHAT"


@dataclass(frozen=True)
class _NotifyGroupContext:
    session: AsyncSession
    dispatch: GatewayDispatchService
    group: BoardGroup
    board_by_id: dict[UUID, Board]
    mentions: set[str]
    is_broadcast: bool
    actor_name: str
    snippet: str
    base_url: str


async def _notify_group_target(
    context: _NotifyGroupContext,
    agent: Agent,
) -> None:
    session_key = agent.openclaw_session_id
    board_id = agent.board_id
    if not session_key or board_id is None:
        return
    board = context.board_by_id.get(board_id)
    if board is None:
        return
    config = await context.dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    header = _group_header(
        is_broadcast=context.is_broadcast,
        mentioned=matches_agent_mention(agent, context.mentions),
    )
    message = (
        f"{header}\n"
        f"Group: {context.group.name}\n"
        f"From: {context.actor_name}\n\n"
        f"{context.snippet}\n\n"
        "Reply via group chat (shared across linked boards):\n"
        f"POST {context.base_url}/api/v1/boards/{board.id}/group-memory\n"
        'Body: {"content":"...","tags":["chat"]}'
    )
    error = await context.dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name=agent.name,
        message=message,
    )
    if error is not None:
        return


async def _notify_group_memory_targets(
    *,
    session: AsyncSession,
    group: BoardGroup,
    memory: BoardGroupMemory,
    actor: ActorContext,
) -> None:
    if not memory.content:
        return

    tags = set(memory.tags or [])
    mentions = extract_mentions(memory.content)
    is_broadcast = "broadcast" in tags or "all" in mentions

    # Fetch group boards + agents.
    boards = await Board.objects.filter_by(board_group_id=group.id).all(session)
    if not boards:
        return
    board_by_id = {board.id: board for board in boards}
    board_ids = list(board_by_id.keys())
    agents = await Agent.objects.by_field_in("board_id", board_ids).all(session)

    targets = _group_chat_targets(
        agents=agents,
        actor=actor,
        is_broadcast=is_broadcast,
        mentions=mentions,
    )

    if not targets:
        return

    actor_name = _group_actor_name(actor)

    snippet = memory.content.strip()
    if len(snippet) > MAX_SNIPPET_LENGTH:
        snippet = f"{snippet[: MAX_SNIPPET_LENGTH - 3]}..."

    base_url = settings.base_url or "http://localhost:8000"

    context = _NotifyGroupContext(
        session=session,
        dispatch=GatewayDispatchService(session),
        group=group,
        board_by_id=board_by_id,
        mentions=mentions,
        is_broadcast=is_broadcast,
        actor_name=actor_name,
        snippet=snippet,
        base_url=base_url,
    )
    for agent in targets.values():
        await _notify_group_target(context, agent)


@group_router.get("", response_model=DefaultLimitOffsetPage[BoardGroupMemoryRead])
async def list_board_group_memory(
    group_id: UUID,
    *,
    is_chat: bool | None = IS_CHAT_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> LimitOffsetPage[BoardGroupMemoryRead]:
    """List board-group memory entries for a specific group."""
    await _require_group_access(session, group_id=group_id, ctx=ctx, write=False)
    statement = (
        BoardGroupMemory.objects.filter_by(board_group_id=group_id)
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardGroupMemory.content))) > 0)
    )
    if is_chat is not None:
        statement = statement.filter(col(BoardGroupMemory.is_chat) == is_chat)
    statement = statement.order_by(col(BoardGroupMemory.created_at).desc())
    return await paginate(session, statement.statement)


@group_router.get("/stream")
async def stream_board_group_memory(
    request: Request,
    group: BoardGroup = GROUP_READ_DEP,
    *,
    since: str | None = SINCE_QUERY,
    is_chat: bool | None = IS_CHAT_QUERY,
) -> EventSourceResponse:
    """Stream memory entries for a board group via server-sent events."""
    since_dt = _parse_since(since) or utcnow()
    last_seen = since_dt

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        nonlocal last_seen
        while True:
            if await request.is_disconnected():
                break
            async with async_session_maker() as s:
                memories = await _fetch_memory_events(
                    s,
                    group.id,
                    last_seen,
                    is_chat=is_chat,
                )
            for memory in memories:
                last_seen = max(memory.created_at, last_seen)
                payload = {"memory": _serialize_memory(memory)}
                yield {"event": "memory", "data": json.dumps(payload)}
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(event_generator(), ping=15)


@group_router.post("", response_model=BoardGroupMemoryRead)
async def create_board_group_memory(
    group_id: UUID,
    payload: BoardGroupMemoryCreate,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> BoardGroupMemory:
    """Create a board-group memory entry and notify chat recipients."""
    group = await _require_group_access(session, group_id=group_id, ctx=ctx, write=True)

    user = await User.objects.by_id(ctx.member.user_id).first(session)
    actor = ActorContext(actor_type="user", user=user)
    tags = set(payload.tags or [])
    is_chat = "chat" in tags
    mentions = extract_mentions(payload.content)
    should_notify = is_chat or "broadcast" in tags or "all" in mentions
    source = payload.source
    if should_notify and not source:
        if actor.actor_type == "agent" and actor.agent:
            source = actor.agent.name
        elif actor.user:
            source = actor.user.preferred_name or actor.user.name or "User"
    memory = BoardGroupMemory(
        board_group_id=group_id,
        content=payload.content,
        tags=payload.tags,
        is_chat=is_chat,
        source=source,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    if should_notify:
        await _notify_group_memory_targets(
            session=session,
            group=group,
            memory=memory,
            actor=actor,
        )
    return memory


@board_router.get(
    "",
    response_model=DefaultLimitOffsetPage[BoardGroupMemoryRead],
    tags=AGENT_BOARD_ROLE_TAGS,
)
async def list_board_group_memory_for_board(
    *,
    is_chat: bool | None = IS_CHAT_QUERY,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[BoardGroupMemoryRead]:
    """List shared memory for the board's linked group.

    Use this for cross-board context and coordination signals.
    """
    group_id = board.board_group_id
    if group_id is None:
        return await paginate(session, BoardGroupMemory.objects.by_ids([]).statement)

    queryset = (
        BoardGroupMemory.objects.filter_by(board_group_id=group_id)
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardGroupMemory.content))) > 0)
    )
    if is_chat is not None:
        queryset = queryset.filter(col(BoardGroupMemory.is_chat) == is_chat)
    queryset = queryset.order_by(col(BoardGroupMemory.created_at).desc())
    return await paginate(session, queryset.statement)


@board_router.get("/stream", tags=AGENT_BOARD_ROLE_TAGS)
async def stream_board_group_memory_for_board(
    request: Request,
    *,
    board: Board = BOARD_READ_DEP,
    since: str | None = SINCE_QUERY,
    is_chat: bool | None = IS_CHAT_QUERY,
) -> EventSourceResponse:
    """Stream linked-group memory via SSE for near-real-time coordination."""
    group_id = board.board_group_id
    since_dt = _parse_since(since) or utcnow()
    last_seen = since_dt

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        nonlocal last_seen
        while True:
            if await request.is_disconnected():
                break
            if group_id is None:
                await asyncio.sleep(2)
                continue
            async with async_session_maker() as session:
                memories = await _fetch_memory_events(
                    session,
                    group_id,
                    last_seen,
                    is_chat=is_chat,
                )
            for memory in memories:
                last_seen = max(memory.created_at, last_seen)
                payload = {"memory": _serialize_memory(memory)}
                yield {"event": "memory", "data": json.dumps(payload)}
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(event_generator(), ping=15)


@board_router.post("", response_model=BoardGroupMemoryRead, tags=AGENT_BOARD_ROLE_TAGS)
async def create_board_group_memory_for_board(
    payload: BoardGroupMemoryCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardGroupMemory:
    """Create shared group memory from a board context.

    When tags/mentions indicate chat or broadcast intent, eligible agents in the
    linked group are notified.
    """
    group_id = board.board_group_id
    if group_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board is not in a board group",
        )
    group = await BoardGroup.objects.by_id(group_id).first(session)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    tags = set(payload.tags or [])
    is_chat = "chat" in tags
    mentions = extract_mentions(payload.content)
    should_notify = is_chat or "broadcast" in tags or "all" in mentions
    source = payload.source
    if should_notify and not source:
        if actor.actor_type == "agent" and actor.agent:
            source = actor.agent.name
        elif actor.user:
            source = actor.user.preferred_name or actor.user.name or "User"
    memory = BoardGroupMemory(
        board_group_id=group_id,
        content=payload.content,
        tags=payload.tags,
        is_chat=is_chat,
        source=source,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    if should_notify:
        await _notify_group_memory_targets(
            session=session,
            group=group,
            memory=memory,
            actor=actor,
        )
    return memory


router.include_router(group_router)
router.include_router(board_router)
