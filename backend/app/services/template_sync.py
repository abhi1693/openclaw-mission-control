"""Gateway template synchronization orchestration."""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.agent_tokens import generate_agent_token, hash_agent_token, verify_agent_token
from app.core.time import utcnow
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, openclaw_call
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.users import User
from app.schemas.gateways import GatewayTemplatesSyncError, GatewayTemplatesSyncResult
from app.services.agent_provisioning import (
    AgentProvisionRequest,
    MainAgentProvisionRequest,
    ProvisionOptions,
    provision_agent,
    provision_main_agent,
)
from app.services.gateway_agents import gateway_agent_session_key

_TOOLS_KV_RE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")
SESSION_KEY_PARTS_MIN = 2
_NON_TRANSIENT_GATEWAY_ERROR_MARKERS = ("unsupported file",)
_TRANSIENT_GATEWAY_ERROR_MARKERS = (
    "connect call failed",
    "connection refused",
    "errno 111",
    "econnrefused",
    "did not receive a valid http response",
    "no route to host",
    "network is unreachable",
    "host is down",
    "name or service not known",
    "received 1012",
    "service restart",
    "http 503",
    "http 502",
    "http 504",
    "temporar",
    "timeout",
    "timed out",
    "connection closed",
    "connection reset",
)

T = TypeVar("T")
_SECURE_RANDOM = random.SystemRandom()
_RUNTIME_TYPE_REFERENCES = (Awaitable, Callable, AsyncSession, Gateway, User, UUID)


@dataclass(frozen=True)
class GatewayTemplateSyncOptions:
    """Runtime options controlling gateway template synchronization."""

    user: User | None
    include_main: bool = True
    reset_sessions: bool = False
    rotate_tokens: bool = False
    force_bootstrap: bool = False
    board_id: UUID | None = None


@dataclass(frozen=True)
class _SyncContext:
    """Shared state passed to sync helper functions."""

    session: AsyncSession
    gateway: Gateway
    config: GatewayClientConfig
    backoff: _GatewayBackoff
    options: GatewayTemplateSyncOptions


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _is_transient_gateway_error(exc: Exception) -> bool:
    if not isinstance(exc, OpenClawGatewayError):
        return False
    message = str(exc).lower()
    if not message:
        return False
    if any(marker in message for marker in _NON_TRANSIENT_GATEWAY_ERROR_MARKERS):
        return False
    return ("503" in message and "websocket" in message) or any(
        marker in message for marker in _TRANSIENT_GATEWAY_ERROR_MARKERS
    )


def _gateway_timeout_message(exc: OpenClawGatewayError) -> str:
    return "Gateway unreachable after 10 minutes (template sync timeout). " f"Last error: {exc}"


class _GatewayBackoff:
    def __init__(
        self,
        *,
        timeout_s: float = 10 * 60,
        base_delay_s: float = 0.75,
        max_delay_s: float = 30.0,
        jitter: float = 0.2,
    ) -> None:
        self._timeout_s = timeout_s
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._jitter = jitter
        self._delay_s = base_delay_s

    def reset(self) -> None:
        self._delay_s = self._base_delay_s

    @staticmethod
    async def _attempt(
        fn: Callable[[], Awaitable[T]],
    ) -> tuple[T | None, OpenClawGatewayError | None]:
        try:
            return await fn(), None
        except OpenClawGatewayError as exc:
            return None, exc

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        # Use per-call deadlines so long-running syncs can still tolerate a later
        # gateway restart without having an already-expired retry window.
        deadline_s = asyncio.get_running_loop().time() + self._timeout_s
        while True:
            value, error = await self._attempt(fn)
            if error is not None:
                exc = error
                if not _is_transient_gateway_error(exc):
                    raise exc
                now = asyncio.get_running_loop().time()
                remaining = deadline_s - now
                if remaining <= 0:
                    raise TimeoutError(_gateway_timeout_message(exc)) from exc

                sleep_s = min(self._delay_s, remaining)
                if self._jitter:
                    sleep_s *= 1.0 + _SECURE_RANDOM.uniform(
                        -self._jitter,
                        self._jitter,
                    )
                sleep_s = max(0.0, min(sleep_s, remaining))
                await asyncio.sleep(sleep_s)
                self._delay_s = min(self._delay_s * 2.0, self._max_delay_s)
                continue
            self.reset()
            if value is None:
                msg = "Gateway retry produced no value without an error"
                raise RuntimeError(msg)
            return value


async def _with_gateway_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    backoff: _GatewayBackoff,
) -> T:
    return await backoff.run(fn)


def _agent_id_from_session_key(session_key: str | None) -> str | None:
    value = (session_key or "").strip()
    if not value:
        return None
    if not value.startswith("agent:"):
        return None
    parts = value.split(":")
    if len(parts) < SESSION_KEY_PARTS_MIN:
        return None
    agent_id = parts[1].strip()
    return agent_id or None


def _extract_agent_id_from_list(items: object) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if not isinstance(item, dict):
            continue
        for key in ("id", "agentId", "agent_id"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _extract_agent_id(payload: object) -> str | None:
    """Extract a default gateway agent id from common list payload shapes."""
    if isinstance(payload, list):
        return _extract_agent_id_from_list(payload)
    if not isinstance(payload, dict):
        return None
    for key in ("defaultId", "default_id", "defaultAgentId", "default_agent_id"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    for key in ("agents", "items", "list", "data"):
        agent_id = _extract_agent_id_from_list(payload.get(key))
        if agent_id:
            return agent_id
    return None


def _gateway_agent_id(agent: Agent) -> str:
    session_key = agent.openclaw_session_id or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= SESSION_KEY_PARTS_MIN and parts[1]:
            return parts[1]
    return _slugify(agent.name)


def _parse_tools_md(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TOOLS_KV_RE.match(line)
        if not match:
            continue
        values[match.group("key")] = match.group("value").strip()
    return values


async def _get_agent_file(
    *,
    agent_gateway_id: str,
    name: str,
    config: GatewayClientConfig,
    backoff: _GatewayBackoff | None = None,
) -> str | None:
    try:

        async def _do_get() -> object:
            return await openclaw_call(
                "agents.files.get",
                {"agentId": agent_gateway_id, "name": name},
                config=config,
            )

        payload = await (backoff.run(_do_get) if backoff else _do_get())
    except OpenClawGatewayError:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content
        file_obj = payload.get("file")
        if isinstance(file_obj, dict):
            nested = file_obj.get("content")
            if isinstance(nested, str):
                return nested
    return None


async def _get_existing_auth_token(
    *,
    agent_gateway_id: str,
    config: GatewayClientConfig,
    backoff: _GatewayBackoff | None = None,
) -> str | None:
    tools = await _get_agent_file(
        agent_gateway_id=agent_gateway_id,
        name="TOOLS.md",
        config=config,
        backoff=backoff,
    )
    if not tools:
        return None
    values = _parse_tools_md(tools)
    token = values.get("AUTH_TOKEN")
    if not token:
        return None
    token = token.strip()
    return token or None


async def _gateway_default_agent_id(
    config: GatewayClientConfig,
    *,
    fallback_session_key: str | None = None,
    backoff: _GatewayBackoff | None = None,
) -> str | None:
    try:

        async def _do_list() -> object:
            return await openclaw_call("agents.list", config=config)

        payload = await (backoff.run(_do_list) if backoff else _do_list())
        agent_id = _extract_agent_id(payload)
        if agent_id:
            return agent_id
    except OpenClawGatewayError:
        pass
    return _agent_id_from_session_key(fallback_session_key)


async def _paused_board_ids(session: AsyncSession, board_ids: list[UUID]) -> set[UUID]:
    if not board_ids:
        return set()

    commands = {"/pause", "/resume"}
    statement = (
        select(BoardMemory.board_id, BoardMemory.content)
        .where(col(BoardMemory.board_id).in_(board_ids))
        .where(col(BoardMemory.is_chat).is_(True))
        .where(func.lower(func.trim(col(BoardMemory.content))).in_(commands))
        .order_by(col(BoardMemory.board_id), col(BoardMemory.created_at).desc())
        # Postgres: DISTINCT ON (board_id) to get latest command per board.
        .distinct(col(BoardMemory.board_id))
    )

    paused: set[UUID] = set()
    for board_id, content in await session.exec(statement):
        cmd = (content or "").strip().lower()
        if cmd == "/pause":
            paused.add(board_id)
    return paused


def _append_sync_error(
    result: GatewayTemplatesSyncResult,
    *,
    message: str,
    agent: Agent | None = None,
    board: Board | None = None,
) -> None:
    result.errors.append(
        GatewayTemplatesSyncError(
            agent_id=agent.id if agent else None,
            agent_name=agent.name if agent else None,
            board_id=board.id if board else None,
            message=message,
        ),
    )


async def _rotate_agent_token(session: AsyncSession, agent: Agent) -> str:
    token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(token)
    agent.updated_at = utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return token


async def _ping_gateway(ctx: _SyncContext, result: GatewayTemplatesSyncResult) -> bool:
    try:

        async def _do_ping() -> object:
            return await openclaw_call("agents.list", config=ctx.config)

        await ctx.backoff.run(_do_ping)
    except (TimeoutError, OpenClawGatewayError) as exc:
        _append_sync_error(result, message=str(exc))
        return False
    else:
        return True


def _base_result(
    gateway: Gateway,
    *,
    include_main: bool,
    reset_sessions: bool,
) -> GatewayTemplatesSyncResult:
    return GatewayTemplatesSyncResult(
        gateway_id=gateway.id,
        include_main=include_main,
        reset_sessions=reset_sessions,
        agents_updated=0,
        agents_skipped=0,
        main_updated=False,
    )


def _boards_by_id(
    boards: list[Board],
    *,
    board_id: UUID | None,
) -> dict[UUID, Board] | None:
    boards_by_id = {board.id: board for board in boards}
    if board_id is None:
        return boards_by_id
    board = boards_by_id.get(board_id)
    if board is None:
        return None
    return {board_id: board}


async def _resolve_agent_auth_token(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
    agent: Agent,
    board: Board | None,
    *,
    agent_gateway_id: str,
) -> tuple[str | None, bool]:
    try:
        auth_token = await _get_existing_auth_token(
            agent_gateway_id=agent_gateway_id,
            config=ctx.config,
            backoff=ctx.backoff,
        )
    except TimeoutError as exc:
        _append_sync_error(result, agent=agent, board=board, message=str(exc))
        return None, True

    if not auth_token:
        if not ctx.options.rotate_tokens:
            result.agents_skipped += 1
            _append_sync_error(
                result,
                agent=agent,
                board=board,
                message=(
                    "Skipping agent: unable to read AUTH_TOKEN from TOOLS.md "
                    "(run with rotate_tokens=true to re-key)."
                ),
            )
            return None, False
        auth_token = await _rotate_agent_token(ctx.session, agent)

    if agent.agent_token_hash and not verify_agent_token(
        auth_token,
        agent.agent_token_hash,
    ):
        if ctx.options.rotate_tokens:
            auth_token = await _rotate_agent_token(ctx.session, agent)
        else:
            _append_sync_error(
                result,
                agent=agent,
                board=board,
                message=(
                    "Warning: AUTH_TOKEN in TOOLS.md does not match backend "
                    "token hash (agent auth may be broken)."
                ),
            )
    return auth_token, False


async def _sync_one_agent(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
    agent: Agent,
    board: Board,
) -> bool:
    auth_token, fatal = await _resolve_agent_auth_token(
        ctx,
        result,
        agent,
        board,
        agent_gateway_id=_gateway_agent_id(agent),
    )
    if fatal:
        return True
    if not auth_token:
        return False
    try:

        async def _do_provision() -> None:
            await provision_agent(
                agent,
                AgentProvisionRequest(
                    board=board,
                    gateway=ctx.gateway,
                    auth_token=auth_token,
                    user=ctx.options.user,
                    options=ProvisionOptions(
                        action="update",
                        force_bootstrap=ctx.options.force_bootstrap,
                        reset_session=ctx.options.reset_sessions,
                    ),
                ),
            )

        await _with_gateway_retry(_do_provision, backoff=ctx.backoff)
        result.agents_updated += 1
    except TimeoutError as exc:  # pragma: no cover - gateway/network dependent
        result.agents_skipped += 1
        _append_sync_error(result, agent=agent, board=board, message=str(exc))
        return True
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        result.agents_skipped += 1
        _append_sync_error(
            result,
            agent=agent,
            board=board,
            message=f"Failed to sync templates: {exc}",
        )
        return False
    else:
        return False


async def _sync_main_agent(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
) -> bool:
    main_session_key = gateway_agent_session_key(ctx.gateway)
    main_agent = (
        await Agent.objects.all()
        .filter(col(Agent.openclaw_session_id) == main_session_key)
        .first(ctx.session)
    )
    if main_agent is None:
        _append_sync_error(
            result,
            message=("Gateway agent record not found; " "skipping gateway agent template sync."),
        )
        return True
    try:
        main_gateway_agent_id = await _gateway_default_agent_id(
            ctx.config,
            fallback_session_key=main_session_key,
            backoff=ctx.backoff,
        )
    except TimeoutError as exc:
        _append_sync_error(result, agent=main_agent, message=str(exc))
        return True
    if not main_gateway_agent_id:
        _append_sync_error(
            result,
            agent=main_agent,
            message="Unable to resolve gateway agent id.",
        )
        return True

    token, fatal = await _resolve_agent_auth_token(
        ctx,
        result,
        main_agent,
        board=None,
        agent_gateway_id=main_gateway_agent_id,
    )
    if fatal:
        return True
    if not token:
        _append_sync_error(
            result,
            agent=main_agent,
            message="Skipping gateway agent: unable to read AUTH_TOKEN from TOOLS.md.",
        )
        return True
    stop_sync = False
    try:

        async def _do_provision_main() -> None:
            await provision_main_agent(
                main_agent,
                MainAgentProvisionRequest(
                    gateway=ctx.gateway,
                    auth_token=token,
                    user=ctx.options.user,
                    session_key=main_session_key,
                    options=ProvisionOptions(
                        action="update",
                        force_bootstrap=ctx.options.force_bootstrap,
                        reset_session=ctx.options.reset_sessions,
                    ),
                ),
            )

        await _with_gateway_retry(_do_provision_main, backoff=ctx.backoff)
    except TimeoutError as exc:  # pragma: no cover - gateway/network dependent
        _append_sync_error(result, agent=main_agent, message=str(exc))
        stop_sync = True
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        _append_sync_error(
            result,
            agent=main_agent,
            message=f"Failed to sync gateway agent templates: {exc}",
        )
    else:
        result.main_updated = True
    return stop_sync


async def sync_gateway_templates(
    session: AsyncSession,
    gateway: Gateway,
    options: GatewayTemplateSyncOptions,
) -> GatewayTemplatesSyncResult:
    """Synchronize AGENTS/TOOLS/etc templates to gateway-connected agents."""
    result = _base_result(
        gateway,
        include_main=options.include_main,
        reset_sessions=options.reset_sessions,
    )
    if not gateway.url:
        _append_sync_error(
            result,
            message="Gateway URL is not configured for this gateway.",
        )
        return result

    ctx = _SyncContext(
        session=session,
        gateway=gateway,
        config=GatewayClientConfig(url=gateway.url, token=gateway.token),
        backoff=_GatewayBackoff(timeout_s=10 * 60),
        options=options,
    )
    if not await _ping_gateway(ctx, result):
        return result

    boards = await Board.objects.filter_by(gateway_id=gateway.id).all(session)
    boards_by_id = _boards_by_id(boards, board_id=options.board_id)
    if boards_by_id is None:
        _append_sync_error(
            result,
            message="Board does not belong to this gateway.",
        )
        return result
    paused_board_ids = await _paused_board_ids(session, list(boards_by_id.keys()))
    if boards_by_id:
        agents = await (
            Agent.objects.by_field_in("board_id", list(boards_by_id.keys()))
            .order_by(col(Agent.created_at).asc())
            .all(session)
        )
    else:
        agents = []

    stop_sync = False
    for agent in agents:
        board = boards_by_id.get(agent.board_id) if agent.board_id is not None else None
        if board is None:
            result.agents_skipped += 1
            _append_sync_error(
                result,
                agent=agent,
                message="Skipping agent: board not found for agent.",
            )
            continue
        if board.id in paused_board_ids:
            result.agents_skipped += 1
            continue
        stop_sync = await _sync_one_agent(ctx, result, agent, board)
        if stop_sync:
            break

    if not stop_sync and options.include_main:
        await _sync_main_agent(ctx, result)
    return result
