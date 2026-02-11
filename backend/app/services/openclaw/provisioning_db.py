"""DB-backed OpenClaw orchestration and agent lifecycle services.

Layering:
- `app.services.openclaw.provisioning` contains gateway-only lifecycle operations (no DB calls).
- This module builds on top of that layer using AsyncSession for token rotation, lead-agent records,
  bulk template synchronization, and API-facing agent lifecycle flows.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status
from sqlalchemy import asc, func, or_
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.core.agent_tokens import verify_agent_token
from app.core.logging import TRACE_LEVEL
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import async_session_maker
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentRead,
    AgentUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.gateways import GatewayTemplatesSyncError, GatewayTemplatesSyncResult
from app.services.activity_log import record_activity
from app.services.openclaw.constants import (
    _TOOLS_KV_RE,
    DEFAULT_HEARTBEAT_CONFIG,
    OFFLINE_AFTER,
)
from app.services.openclaw.db_agent_state import (
    mark_provision_complete,
    mark_provision_requested,
    mint_agent_token,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    optional_gateway_client_config,
    require_gateway_for_board,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    ensure_session,
    send_message,
)
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.internal.retry import GatewayBackoff
from app.services.openclaw.internal.session_keys import (
    board_agent_session_key,
    board_lead_session_key,
)
from app.services.openclaw.policies import OpenClawAuthorizationPolicy
from app.services.openclaw.provisioning import (
    OpenClawGatewayControlPlane,
    OpenClawGatewayProvisioner,
)
from app.services.openclaw.shared import GatewayAgentIdentity
from app.services.organizations import (
    OrganizationContext,
    get_active_membership,
    get_org_owner_user,
    has_board_access,
    is_org_admin,
    list_accessible_board_ids,
    require_board_access,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlalchemy.sql.elements import ColumnElement
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

    from app.models.users import User


_T = TypeVar("_T")


@dataclass(frozen=True)
class GatewayTemplateSyncOptions:
    """Runtime options controlling gateway template synchronization."""

    user: User | None
    include_main: bool = True
    reset_sessions: bool = False
    rotate_tokens: bool = False
    force_bootstrap: bool = False
    board_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LeadAgentOptions:
    """Optional overrides for board-lead provisioning behavior."""

    agent_name: str | None = None
    identity_profile: dict[str, str] | None = None
    action: str = "provision"


@dataclass(frozen=True, slots=True)
class LeadAgentRequest:
    """Inputs required to ensure or provision a board lead agent."""

    board: Board
    gateway: Gateway
    config: GatewayClientConfig
    user: User | None
    options: LeadAgentOptions = field(default_factory=LeadAgentOptions)


class OpenClawProvisioningService(OpenClawDBService):
    """DB-backed provisioning workflows (bulk template sync, lead-agent record)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._gateway = OpenClawGatewayProvisioner()

    @staticmethod
    def lead_session_key(board: Board) -> str:
        return board_lead_session_key(board.id)

    @staticmethod
    def lead_agent_name(_: Board) -> str:
        return "Lead Agent"

    async def ensure_board_lead_agent(
        self,
        *,
        request: LeadAgentRequest,
    ) -> tuple[Agent, bool]:
        """Ensure a board has a lead agent; return `(agent, created)`."""
        board = request.board
        config_options = request.options

        existing = (
            await self.session.exec(
                select(Agent)
                .where(Agent.board_id == board.id)
                .where(col(Agent.is_board_lead).is_(True)),
            )
        ).first()
        if existing:
            desired_name = config_options.agent_name or self.lead_agent_name(board)
            changed = False
            if existing.name != desired_name:
                existing.name = desired_name
                changed = True
            if existing.gateway_id != request.gateway.id:
                existing.gateway_id = request.gateway.id
                changed = True
            desired_session_key = self.lead_session_key(board)
            if existing.openclaw_session_id != desired_session_key:
                existing.openclaw_session_id = desired_session_key
                changed = True
            if changed:
                existing.updated_at = utcnow()
                self.session.add(existing)
                await self.session.commit()
                await self.session.refresh(existing)
            return existing, False

        merged_identity_profile: dict[str, Any] = {
            "role": "Board Lead",
            "communication_style": "direct, concise, practical",
            "emoji": ":gear:",
        }
        if config_options.identity_profile:
            merged_identity_profile.update(
                {
                    key: value.strip()
                    for key, value in config_options.identity_profile.items()
                    if value.strip()
                },
            )

        agent = Agent(
            name=config_options.agent_name or self.lead_agent_name(board),
            board_id=board.id,
            gateway_id=request.gateway.id,
            is_board_lead=True,
            heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
            identity_profile=merged_identity_profile,
            openclaw_session_id=self.lead_session_key(board),
        )
        raw_token = mint_agent_token(agent)
        mark_provision_requested(agent, action=config_options.action, status="provisioning")
        await self.add_commit_refresh(agent)

        # Strict behavior: provisioning errors surface to the caller. The DB row exists
        # so a later retry can succeed with the same deterministic identity/session key.
        await self._gateway.apply_agent_lifecycle(
            agent=agent,
            gateway=request.gateway,
            board=board,
            auth_token=raw_token,
            user=request.user,
            action=config_options.action,
            wake=True,
            deliver_wakeup=True,
        )

        mark_provision_complete(agent, status="online")
        await self.add_commit_refresh(agent)

        return agent, True

    async def sync_gateway_templates(
        self,
        gateway: Gateway,
        options: GatewayTemplateSyncOptions,
    ) -> GatewayTemplatesSyncResult:
        """Synchronize AGENTS/TOOLS/etc templates to gateway-connected agents."""
        template_user = options.user
        if template_user is None:
            template_user = await get_org_owner_user(
                self.session,
                organization_id=gateway.organization_id,
            )
            options = GatewayTemplateSyncOptions(
                user=template_user,
                include_main=options.include_main,
                reset_sessions=options.reset_sessions,
                rotate_tokens=options.rotate_tokens,
                force_bootstrap=options.force_bootstrap,
                board_id=options.board_id,
            )

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

        control_plane = OpenClawGatewayControlPlane(
            GatewayClientConfig(url=gateway.url, token=gateway.token),
        )
        ctx = _SyncContext(
            session=self.session,
            gateway=gateway,
            control_plane=control_plane,
            backoff=GatewayBackoff(timeout_s=10 * 60, timeout_context="template sync"),
            options=options,
            provisioner=self._gateway,
        )
        if not await _ping_gateway(ctx, result):
            return result

        boards = await Board.objects.filter_by(gateway_id=gateway.id).all(self.session)
        boards_by_id = _boards_by_id(boards, board_id=options.board_id)
        if boards_by_id is None:
            _append_sync_error(
                result,
                message="Board does not belong to this gateway.",
            )
            return result
        paused_board_ids = await _paused_board_ids(self.session, list(boards_by_id.keys()))
        if boards_by_id:
            agents = await (
                Agent.objects.by_field_in("board_id", list(boards_by_id.keys()))
                .order_by(col(Agent.created_at).asc())
                .all(self.session)
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


@dataclass(frozen=True)
class _SyncContext:
    session: AsyncSession
    gateway: Gateway
    control_plane: OpenClawGatewayControlPlane
    backoff: GatewayBackoff
    options: GatewayTemplateSyncOptions
    provisioner: OpenClawGatewayProvisioner


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
    control_plane: OpenClawGatewayControlPlane,
    backoff: GatewayBackoff | None = None,
) -> str | None:
    try:

        async def _do_get() -> object:
            return await control_plane.get_agent_file_payload(agent_id=agent_gateway_id, name=name)

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
    control_plane: OpenClawGatewayControlPlane,
    backoff: GatewayBackoff | None = None,
) -> str | None:
    tools = await _get_agent_file(
        agent_gateway_id=agent_gateway_id,
        name="TOOLS.md",
        control_plane=control_plane,
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
    token = mint_agent_token(agent)
    agent.updated_at = utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return token


async def _ping_gateway(ctx: _SyncContext, result: GatewayTemplatesSyncResult) -> bool:
    try:

        async def _do_ping() -> object:
            return await ctx.control_plane.health()

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
            control_plane=ctx.control_plane,
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
        agent_gateway_id=_agent_key(agent),
    )
    if fatal:
        return True
    if not auth_token:
        return False
    try:

        async def _do_provision() -> bool:
            await ctx.provisioner.apply_agent_lifecycle(
                agent=agent,
                gateway=ctx.gateway,
                board=board,
                auth_token=auth_token,
                user=ctx.options.user,
                action="update",
                force_bootstrap=ctx.options.force_bootstrap,
                reset_session=ctx.options.reset_sessions,
                wake=False,
            )
            return True

        await ctx.backoff.run(_do_provision)
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
    main_agent = (
        await Agent.objects.all()
        .filter(col(Agent.gateway_id) == ctx.gateway.id)
        .filter(col(Agent.board_id).is_(None))
        .first(ctx.session)
    )
    if main_agent is None:
        _append_sync_error(
            result,
            message="Gateway agent record not found; skipping gateway agent template sync.",
        )
        return True

    main_gateway_agent_id = GatewayAgentIdentity.openclaw_agent_id(ctx.gateway)
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

        async def _do_provision_main() -> bool:
            await ctx.provisioner.apply_agent_lifecycle(
                agent=main_agent,
                gateway=ctx.gateway,
                board=None,
                auth_token=token,
                user=ctx.options.user,
                action="update",
                force_bootstrap=ctx.options.force_bootstrap,
                reset_session=ctx.options.reset_sessions,
                wake=False,
            )
            return True

        await ctx.backoff.run(_do_provision_main)
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


class ActorContextLike(Protocol):
    """Minimal actor context contract consumed by lifecycle APIs."""

    actor_type: Literal["user", "agent"]
    user: User | None
    agent: Agent | None


@dataclass(frozen=True, slots=True)
class AgentUpdateOptions:
    """Runtime options for update-and-reprovision flows."""

    force: bool
    user: User | None
    context: OrganizationContext


@dataclass(frozen=True, slots=True)
class AgentUpdateProvisionTarget:
    """Resolved target for an update provision operation."""

    is_main_agent: bool
    board: Board | None
    gateway: Gateway


@dataclass(frozen=True, slots=True)
class AgentUpdateProvisionRequest:
    """Provision request payload for agent updates."""

    target: AgentUpdateProvisionTarget
    raw_token: str
    user: User | None
    force_bootstrap: bool


class AgentLifecycleService(OpenClawDBService):
    """Async service encapsulating agent lifecycle behavior for API routes."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def parse_since(value: str | None) -> datetime | None:
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

    @staticmethod
    def slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or uuid4().hex

    @classmethod
    def resolve_session_key(cls, agent: Agent) -> str:
        """Resolve the gateway session key for an agent.

        Notes:
        - For board-scoped agents, default to a UUID-based key to avoid name collisions.
        """

        existing = (agent.openclaw_session_id or "").strip()
        if agent.board_id is None:
            # Gateway-main agents must have an explicit deterministic key (set elsewhere).
            if existing:
                return existing
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gateway main agent session key is required",
            )
        if agent.is_board_lead:
            return board_lead_session_key(agent.board_id)
        return board_agent_session_key(agent.id)

    @classmethod
    def workspace_path(cls, agent_name: str, workspace_root: str | None) -> str:
        if not workspace_root:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gateway workspace_root is required",
            )
        root = workspace_root.rstrip("/")
        return f"{root}/workspace-{cls.slugify(agent_name)}"

    async def require_board(
        self,
        board_id: UUID | str | None,
        *,
        user: User | None = None,
        write: bool = False,
    ) -> Board:
        if not board_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="board_id is required",
            )
        board = await Board.objects.by_id(board_id).first(self.session)
        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Board not found",
            )
        if user is not None:
            await require_board_access(self.session, user=user, board=board, write=write)
        return board

    async def require_gateway(
        self,
        board: Board,
    ) -> tuple[Gateway, GatewayClientConfig]:
        gateway = await require_gateway_for_board(
            self.session,
            board,
            require_workspace_root=True,
        )
        return gateway, gateway_client_config(gateway)

    @staticmethod
    def is_gateway_main(agent: Agent) -> bool:
        return agent.board_id is None

    @classmethod
    def to_agent_read(cls, agent: Agent) -> AgentRead:
        model = AgentRead.model_validate(agent, from_attributes=True)
        return model.model_copy(
            update={"is_gateway_main": cls.is_gateway_main(agent)},
        )

    @staticmethod
    def coerce_agent_items(items: Sequence[Any]) -> list[Agent]:
        agents: list[Agent] = []
        for item in items:
            if not isinstance(item, Agent):
                msg = "Expected Agent items from paginated query"
                raise TypeError(msg)
            agents.append(item)
        return agents

    async def get_main_agent_gateway(self, agent: Agent) -> Gateway | None:
        if agent.board_id is not None:
            return None
        return await Gateway.objects.by_id(agent.gateway_id).first(self.session)

    @classmethod
    def with_computed_status(cls, agent: Agent) -> Agent:
        now = utcnow()
        if agent.status in {"deleting", "updating"}:
            return agent
        if agent.last_seen_at is None:
            agent.status = "provisioning"
        elif now - agent.last_seen_at > OFFLINE_AFTER:
            agent.status = "offline"
        return agent

    @classmethod
    def serialize_agent(cls, agent: Agent) -> dict[str, object]:
        return cls.to_agent_read(cls.with_computed_status(agent)).model_dump(mode="json")

    async def fetch_agent_events(
        self,
        board_id: UUID | None,
        since: datetime,
    ) -> list[Agent]:
        statement = select(Agent)
        if board_id:
            statement = statement.where(col(Agent.board_id) == board_id)
        statement = statement.where(
            or_(
                col(Agent.updated_at) >= since,
                col(Agent.last_seen_at) >= since,
            ),
        ).order_by(asc(col(Agent.updated_at)))
        return list(await self.session.exec(statement))

    async def require_user_context(self, user: User | None) -> OrganizationContext:
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        member = await get_active_membership(self.session, user)
        if member is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        organization = await Organization.objects.by_id(member.organization_id).first(self.session)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return OrganizationContext(organization=organization, member=member)

    async def require_agent_access(
        self,
        *,
        agent: Agent,
        ctx: OrganizationContext,
        write: bool,
    ) -> None:
        if agent.board_id is None:
            OpenClawAuthorizationPolicy.require_org_admin(is_admin=is_org_admin(ctx.member))
            gateway = await self.get_main_agent_gateway(agent)
            OpenClawAuthorizationPolicy.require_gateway_in_org(
                gateway=gateway,
                organization_id=ctx.organization.id,
            )
            return

        board = await Board.objects.by_id(agent.board_id).first(self.session)
        board = OpenClawAuthorizationPolicy.require_board_in_org(
            board=board,
            organization_id=ctx.organization.id,
        )
        allowed = await has_board_access(
            self.session,
            member=ctx.member,
            board=board,
            write=write,
        )
        OpenClawAuthorizationPolicy.require_board_write_access(allowed=allowed)

    @staticmethod
    def record_heartbeat(session: AsyncSession, agent: Agent) -> None:
        record_activity(
            session,
            event_type="agent.heartbeat",
            message=f"Heartbeat received from {agent.name}.",
            agent_id=agent.id,
        )

    @staticmethod
    def record_instruction_failure(
        session: AsyncSession,
        agent: Agent,
        error: str,
        action: str,
    ) -> None:
        action_label = action.replace("_", " ").capitalize()
        record_activity(
            session,
            event_type=f"agent.{action}.failed",
            message=f"{action_label} message failed: {error}",
            agent_id=agent.id,
        )

    async def coerce_agent_create_payload(
        self,
        payload: AgentCreate,
        actor: ActorContextLike,
    ) -> AgentCreate:
        if actor.actor_type == "user":
            ctx = await self.require_user_context(actor.user)
            OpenClawAuthorizationPolicy.require_org_admin(is_admin=is_org_admin(ctx.member))
            return payload

        if actor.actor_type == "agent":
            board_id = OpenClawAuthorizationPolicy.resolve_board_lead_create_board_id(
                actor_agent=actor.agent,
                requested_board_id=payload.board_id,
            )
            return AgentCreate(**{**payload.model_dump(), "board_id": board_id})

        return payload

    async def ensure_unique_agent_name(
        self,
        *,
        board: Board,
        gateway: Gateway,
        requested_name: str,
    ) -> None:
        if not requested_name:
            return

        existing = (
            await self.session.exec(
                select(Agent)
                .where(Agent.board_id == board.id)
                .where(col(Agent.name).ilike(requested_name)),
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An agent with this name already exists on this board.",
            )

        existing_gateway = (
            await self.session.exec(
                select(Agent)
                .join(Board, col(Agent.board_id) == col(Board.id))
                .where(col(Board.gateway_id) == gateway.id)
                .where(col(Agent.name).ilike(requested_name)),
            )
        ).first()
        if existing_gateway:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An agent with this name already exists in this gateway workspace.",
            )

    async def persist_new_agent(
        self,
        *,
        data: dict[str, Any],
    ) -> tuple[Agent, str]:
        agent = Agent.model_validate(data)
        raw_token = mint_agent_token(agent)
        mark_provision_requested(agent, action="provision", status="provisioning")
        agent.openclaw_session_id = self.resolve_session_key(agent)
        await self.add_commit_refresh(agent)
        return agent, raw_token

    async def _apply_gateway_provisioning(
        self,
        *,
        agent: Agent,
        target: AgentUpdateProvisionTarget,
        auth_token: str,
        user: User | None,
        action: str,
        wakeup_verb: str,
        force_bootstrap: bool,
        raise_gateway_errors: bool,
    ) -> None:
        self.logger.log(
            TRACE_LEVEL,
            "agent.provision.start action=%s agent_id=%s target_main=%s",
            action,
            agent.id,
            target.is_main_agent,
        )
        try:
            if not target.is_main_agent and target.board is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="board is required for non-main agent provisioning",
                )
            template_user = user
            if target.is_main_agent and template_user is None:
                template_user = await get_org_owner_user(
                    self.session,
                    organization_id=target.gateway.organization_id,
                )
                if template_user is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            "User context is required to provision the gateway main agent "
                            "(org owner not found)."
                        ),
                    )
            await OpenClawGatewayProvisioner().apply_agent_lifecycle(
                agent=agent,
                gateway=target.gateway,
                board=target.board if not target.is_main_agent else None,
                auth_token=auth_token,
                user=template_user,
                action=action,
                force_bootstrap=force_bootstrap,
                reset_session=True,
                wake=True,
                deliver_wakeup=True,
                wakeup_verb=wakeup_verb,
            )
            mark_provision_complete(agent, status="online", clear_confirm_token=True)
            self.session.add(agent)
            await self.session.commit()
            record_activity(
                self.session,
                event_type=f"agent.{action}.direct",
                message=f"{action.capitalize()}d directly for {agent.name}.",
                agent_id=agent.id,
            )
            record_activity(
                self.session,
                event_type="agent.wakeup.sent",
                message=f"Wakeup message sent to {agent.name}.",
                agent_id=agent.id,
            )
            await self.session.commit()
            self.logger.info(
                "agent.provision.success action=%s agent_id=%s",
                action,
                agent.id,
            )
        except OpenClawGatewayError as exc:
            self.record_instruction_failure(
                self.session,
                agent,
                str(exc),
                action,
            )
            await self.session.commit()
            self.logger.error(
                "agent.provision.gateway_error action=%s agent_id=%s error=%s",
                action,
                agent.id,
                str(exc),
            )
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway {action} failed: {exc}",
                ) from exc
        except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
            self.record_instruction_failure(
                self.session,
                agent,
                str(exc),
                action,
            )
            await self.session.commit()
            self.logger.critical(
                "agent.provision.runtime_error action=%s agent_id=%s error=%s",
                action,
                agent.id,
                str(exc),
            )
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Unexpected error {action}ing agent provisioning.",
                ) from exc

    async def provision_new_agent(
        self,
        *,
        agent: Agent,
        board: Board,
        gateway: Gateway,
        auth_token: str,
        user: User | None,
        force_bootstrap: bool,
    ) -> None:
        await self._apply_gateway_provisioning(
            agent=agent,
            target=AgentUpdateProvisionTarget(is_main_agent=False, board=board, gateway=gateway),
            auth_token=auth_token,
            user=user,
            action="provision",
            wakeup_verb="provisioned",
            force_bootstrap=force_bootstrap,
            raise_gateway_errors=True,
        )

    async def validate_agent_update_inputs(
        self,
        *,
        ctx: OrganizationContext,
        updates: dict[str, Any],
        make_main: bool | None,
    ) -> None:
        if make_main:
            OpenClawAuthorizationPolicy.require_org_admin(is_admin=is_org_admin(ctx.member))
        if "status" in updates:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="status is controlled by agent heartbeat",
            )
        if "board_id" in updates and updates["board_id"] is not None:
            new_board = await self.require_board(updates["board_id"])
            OpenClawAuthorizationPolicy.require_board_in_org(
                board=new_board,
                organization_id=ctx.organization.id,
            )
            allowed = await has_board_access(
                self.session,
                member=ctx.member,
                board=new_board,
                write=True,
            )
            OpenClawAuthorizationPolicy.require_board_write_access(allowed=allowed)

    async def apply_agent_update_mutations(
        self,
        *,
        agent: Agent,
        updates: dict[str, Any],
        make_main: bool | None,
    ) -> tuple[Gateway | None, Gateway | None]:
        main_gateway = await self.get_main_agent_gateway(agent)
        gateway_for_main: Gateway | None = None

        if make_main:
            board_source = updates.get("board_id") or agent.board_id
            board_for_main = await self.require_board(board_source)
            gateway_for_main, _ = await self.require_gateway(board_for_main)
            updates["board_id"] = None
            updates["gateway_id"] = gateway_for_main.id
            agent.is_board_lead = False
            agent.openclaw_session_id = GatewayAgentIdentity.session_key(gateway_for_main)
            main_gateway = gateway_for_main
        elif make_main is not None:
            if "board_id" not in updates or updates["board_id"] is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "board_id is required when converting a gateway-main agent "
                        "to board scope"
                    ),
                )
            board = await self.require_board(updates["board_id"])
            if board.gateway_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Board gateway_id is required",
                )
            updates["gateway_id"] = board.gateway_id
            agent.openclaw_session_id = None

        if make_main is None and "board_id" in updates:
            board = await self.require_board(updates["board_id"])
            if board.gateway_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Board gateway_id is required",
                )
            updates["gateway_id"] = board.gateway_id
        for key, value in updates.items():
            setattr(agent, key, value)

        if make_main is None and main_gateway is not None:
            agent.board_id = None
            agent.gateway_id = main_gateway.id
            agent.is_board_lead = False
        if make_main is False and agent.board_id is not None:
            board = await self.require_board(agent.board_id)
            if board.gateway_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Board gateway_id is required",
                )
            agent.gateway_id = board.gateway_id
        agent.updated_at = utcnow()
        if agent.heartbeat_config is None:
            agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return main_gateway, gateway_for_main

    async def resolve_agent_update_target(
        self,
        *,
        agent: Agent,
        make_main: bool | None,
        main_gateway: Gateway | None,
        gateway_for_main: Gateway | None,
    ) -> AgentUpdateProvisionTarget:
        if make_main:
            if gateway_for_main is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Gateway agent requires a gateway configuration",
                )
            return AgentUpdateProvisionTarget(
                is_main_agent=True,
                board=None,
                gateway=gateway_for_main,
            )

        if make_main is None and agent.board_id is None and main_gateway is not None:
            return AgentUpdateProvisionTarget(
                is_main_agent=True,
                board=None,
                gateway=main_gateway,
            )

        if agent.board_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="board_id is required for non-main agents",
            )
        board = await self.require_board(agent.board_id)
        gateway, _client_config = await self.require_gateway(board)
        return AgentUpdateProvisionTarget(
            is_main_agent=False,
            board=board,
            gateway=gateway,
        )

    @staticmethod
    def mark_agent_update_pending(agent: Agent) -> str:
        raw_token = mint_agent_token(agent)
        mark_provision_requested(agent, action="update", status="updating")
        return raw_token

    async def provision_updated_agent(
        self,
        *,
        agent: Agent,
        request: AgentUpdateProvisionRequest,
    ) -> None:
        await self._apply_gateway_provisioning(
            agent=agent,
            target=request.target,
            auth_token=request.raw_token,
            user=request.user,
            action="update",
            wakeup_verb="updated",
            force_bootstrap=request.force_bootstrap,
            raise_gateway_errors=True,
        )

    @staticmethod
    def heartbeat_lookup_statement(payload: AgentHeartbeatCreate) -> SelectOfScalar[Agent]:
        statement = Agent.objects.filter_by(name=payload.name).statement
        if payload.board_id is not None:
            statement = statement.where(Agent.board_id == payload.board_id)
        return statement

    async def create_agent_from_heartbeat(
        self,
        *,
        payload: AgentHeartbeatCreate,
        actor: ActorContextLike,
    ) -> Agent:
        if actor.actor_type == "agent":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if actor.actor_type == "user":
            ctx = await self.require_user_context(actor.user)
            OpenClawAuthorizationPolicy.require_org_admin(is_admin=is_org_admin(ctx.member))

        board = await self.require_board(
            payload.board_id,
            user=actor.user,
            write=True,
        )
        gateway, _client_config = await self.require_gateway(board)
        data: dict[str, Any] = {
            "name": payload.name,
            "board_id": board.id,
            "gateway_id": gateway.id,
            "heartbeat_config": DEFAULT_HEARTBEAT_CONFIG.copy(),
        }
        agent, raw_token = await self.persist_new_agent(data=data)
        await self.provision_new_agent(
            agent=agent,
            board=board,
            gateway=gateway,
            auth_token=raw_token,
            user=actor.user,
            force_bootstrap=False,
        )
        return agent

    async def handle_existing_user_heartbeat_agent(
        self,
        *,
        agent: Agent,
        user: User | None,
    ) -> None:
        ctx = await self.require_user_context(user)
        await self.require_agent_access(agent=agent, ctx=ctx, write=True)

        if agent.agent_token_hash is not None:
            return

        raw_token = mint_agent_token(agent)
        mark_provision_requested(agent, action="provision", status="provisioning")
        await self.add_commit_refresh(agent)
        board = await self.require_board(
            str(agent.board_id) if agent.board_id else None,
            user=user,
            write=True,
        )
        gateway, _client_config = await self.require_gateway(board)
        await self.provision_new_agent(
            agent=agent,
            board=board,
            gateway=gateway,
            auth_token=raw_token,
            user=user,
            force_bootstrap=False,
        )

    async def ensure_heartbeat_session_key(
        self,
        *,
        agent: Agent,
        actor: ActorContextLike,
    ) -> None:
        _ = actor
        if agent.board_id is None:
            return
        desired = self.resolve_session_key(agent)
        existing = (agent.openclaw_session_id or "").strip()
        if existing == desired:
            return
        agent.openclaw_session_id = desired
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)

    async def commit_heartbeat(
        self,
        *,
        agent: Agent,
        status_value: str | None,
    ) -> AgentRead:
        if status_value:
            agent.status = status_value
        elif agent.status == "provisioning":
            agent.status = "online"
        agent.last_seen_at = utcnow()
        agent.updated_at = utcnow()
        self.record_heartbeat(self.session, agent)
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return self.to_agent_read(self.with_computed_status(agent))

    async def list_agents(
        self,
        *,
        board_id: UUID | None,
        gateway_id: UUID | None,
        ctx: OrganizationContext,
    ) -> LimitOffsetPage[AgentRead]:
        board_ids = await list_accessible_board_ids(self.session, member=ctx.member, write=False)
        if board_id is not None:
            OpenClawAuthorizationPolicy.require_board_write_access(
                allowed=board_id in set(board_ids),
            )
        base_filters: list[ColumnElement[bool]] = []
        if board_ids:
            base_filters.append(col(Agent.board_id).in_(board_ids))
        if is_org_admin(ctx.member):
            gateways = await Gateway.objects.filter_by(
                organization_id=ctx.organization.id,
            ).all(self.session)
            gateway_ids = [gateway.id for gateway in gateways]
            if gateway_ids:
                base_filters.append(
                    (col(Agent.gateway_id).in_(gateway_ids)) & (col(Agent.board_id).is_(None)),
                )
        if base_filters:
            if len(base_filters) == 1:
                statement = select(Agent).where(base_filters[0])
            else:
                statement = select(Agent).where(or_(*base_filters))
        else:
            statement = select(Agent).where(col(Agent.id).is_(None))
        if board_id is not None:
            statement = statement.where(col(Agent.board_id) == board_id)
        if gateway_id is not None:
            gateway = await Gateway.objects.by_id(gateway_id).first(self.session)
            if gateway is None or gateway.organization_id != ctx.organization.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            gateway_board_ids = select(Board.id).where(col(Board.gateway_id) == gateway_id)
            statement = statement.where(
                or_(
                    col(Agent.board_id).in_(gateway_board_ids),
                    (col(Agent.gateway_id) == gateway_id) & (col(Agent.board_id).is_(None)),
                ),
            )
        statement = statement.order_by(col(Agent.created_at).desc())

        def _transform(items: Sequence[Any]) -> Sequence[Any]:
            agents = self.coerce_agent_items(items)
            return [self.to_agent_read(self.with_computed_status(agent)) for agent in agents]

        return await paginate(self.session, statement, transformer=_transform)

    async def stream_agents(
        self,
        *,
        request: Request,
        board_id: UUID | None,
        since: str | None,
        ctx: OrganizationContext,
    ) -> EventSourceResponse:
        since_dt = self.parse_since(since) or utcnow()
        last_seen = since_dt
        board_ids = await list_accessible_board_ids(self.session, member=ctx.member, write=False)
        allowed_ids = set(board_ids)
        if board_id is not None:
            OpenClawAuthorizationPolicy.require_board_write_access(allowed=board_id in allowed_ids)

        async def event_generator() -> AsyncIterator[dict[str, str]]:
            nonlocal last_seen
            while True:
                if await request.is_disconnected():
                    break
                async with async_session_maker() as stream_session:
                    stream_service = AgentLifecycleService(stream_session)
                    stream_service.logger = self.logger
                    if board_id is not None:
                        agents = await stream_service.fetch_agent_events(
                            board_id,
                            last_seen,
                        )
                    elif allowed_ids:
                        agents = await stream_service.fetch_agent_events(None, last_seen)
                        agents = [agent for agent in agents if agent.board_id in allowed_ids]
                    else:
                        agents = []
                for agent in agents:
                    updated_at = agent.updated_at or agent.last_seen_at or utcnow()
                    last_seen = max(updated_at, last_seen)
                    payload = {"agent": self.serialize_agent(agent)}
                    yield {"event": "agent", "data": json.dumps(payload)}
                await asyncio.sleep(2)

        return EventSourceResponse(event_generator(), ping=15)

    async def create_agent(
        self,
        *,
        payload: AgentCreate,
        actor: ActorContextLike,
    ) -> AgentRead:
        self.logger.log(
            TRACE_LEVEL,
            "agent.create.start actor_type=%s board_id=%s",
            actor.actor_type,
            payload.board_id,
        )
        payload = await self.coerce_agent_create_payload(payload, actor)

        board = await self.require_board(
            payload.board_id,
            user=actor.user if actor.actor_type == "user" else None,
            write=actor.actor_type == "user",
        )
        gateway, _client_config = await self.require_gateway(board)
        data = payload.model_dump()
        data["gateway_id"] = gateway.id
        requested_name = (data.get("name") or "").strip()
        await self.ensure_unique_agent_name(
            board=board,
            gateway=gateway,
            requested_name=requested_name,
        )
        agent, raw_token = await self.persist_new_agent(data=data)
        await self.provision_new_agent(
            agent=agent,
            board=board,
            gateway=gateway,
            auth_token=raw_token,
            user=actor.user if actor.actor_type == "user" else None,
            force_bootstrap=False,
        )
        self.logger.info("agent.create.success agent_id=%s board_id=%s", agent.id, board.id)
        return self.to_agent_read(self.with_computed_status(agent))

    async def get_agent(
        self,
        *,
        agent_id: str,
        ctx: OrganizationContext,
    ) -> AgentRead:
        agent = await Agent.objects.by_id(agent_id).first(self.session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await self.require_agent_access(agent=agent, ctx=ctx, write=False)
        return self.to_agent_read(self.with_computed_status(agent))

    async def update_agent(
        self,
        *,
        agent_id: str,
        payload: AgentUpdate,
        options: AgentUpdateOptions,
    ) -> AgentRead:
        self.logger.log(
            TRACE_LEVEL,
            "agent.update.start agent_id=%s force=%s",
            agent_id,
            options.force,
        )
        agent = await Agent.objects.by_id(agent_id).first(self.session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await self.require_agent_access(agent=agent, ctx=options.context, write=True)
        updates = payload.model_dump(exclude_unset=True)
        make_main = updates.pop("is_gateway_main", None)
        await self.validate_agent_update_inputs(
            ctx=options.context,
            updates=updates,
            make_main=make_main,
        )
        if not updates and not options.force and make_main is None:
            return self.to_agent_read(self.with_computed_status(agent))
        main_gateway, gateway_for_main = await self.apply_agent_update_mutations(
            agent=agent,
            updates=updates,
            make_main=make_main,
        )
        target = await self.resolve_agent_update_target(
            agent=agent,
            make_main=make_main,
            main_gateway=main_gateway,
            gateway_for_main=gateway_for_main,
        )
        raw_token = self.mark_agent_update_pending(agent)
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        provision_request = AgentUpdateProvisionRequest(
            target=target,
            raw_token=raw_token,
            user=options.user,
            force_bootstrap=options.force,
        )
        await self.provision_updated_agent(
            agent=agent,
            request=provision_request,
        )
        self.logger.info("agent.update.success agent_id=%s", agent.id)
        return self.to_agent_read(self.with_computed_status(agent))

    async def heartbeat_agent(
        self,
        *,
        agent_id: str,
        payload: AgentHeartbeat,
        actor: ActorContextLike,
    ) -> AgentRead:
        self.logger.log(
            TRACE_LEVEL,
            "agent.heartbeat.start agent_id=%s actor_type=%s",
            agent_id,
            actor.actor_type,
        )
        agent = await Agent.objects.by_id(agent_id).first(self.session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if actor.actor_type == "agent":
            OpenClawAuthorizationPolicy.require_same_agent_actor(
                actor_agent_id=actor.agent.id if actor.agent else None,
                target_agent_id=agent.id,
            )
        if actor.actor_type == "user":
            ctx = await self.require_user_context(actor.user)
            OpenClawAuthorizationPolicy.require_org_admin(is_admin=is_org_admin(ctx.member))
            await self.require_agent_access(agent=agent, ctx=ctx, write=True)
        return await self.commit_heartbeat(
            agent=agent,
            status_value=payload.status,
        )

    async def heartbeat_or_create_agent(
        self,
        *,
        payload: AgentHeartbeatCreate,
        actor: ActorContextLike,
    ) -> AgentRead:
        self.logger.log(
            TRACE_LEVEL,
            "agent.heartbeat_or_create.start actor_type=%s name=%s board_id=%s",
            actor.actor_type,
            payload.name,
            payload.board_id,
        )
        if actor.actor_type == "agent" and actor.agent:
            return await self.heartbeat_agent(
                agent_id=str(actor.agent.id),
                payload=AgentHeartbeat(status=payload.status),
                actor=actor,
            )

        agent = (await self.session.exec(self.heartbeat_lookup_statement(payload))).first()
        if agent is None:
            agent = await self.create_agent_from_heartbeat(
                payload=payload,
                actor=actor,
            )
        elif actor.actor_type == "user":
            await self.handle_existing_user_heartbeat_agent(
                agent=agent,
                user=actor.user,
            )
        elif actor.actor_type == "agent":
            OpenClawAuthorizationPolicy.require_same_agent_actor(
                actor_agent_id=actor.agent.id if actor.agent else None,
                target_agent_id=agent.id,
            )

        await self.ensure_heartbeat_session_key(
            agent=agent,
            actor=actor,
        )
        return await self.commit_heartbeat(
            agent=agent,
            status_value=payload.status,
        )

    async def delete_agent(
        self,
        *,
        agent_id: str,
        ctx: OrganizationContext,
    ) -> OkResponse:
        self.logger.log(TRACE_LEVEL, "agent.delete.start agent_id=%s", agent_id)
        agent = await Agent.objects.by_id(agent_id).first(self.session)
        if agent is None:
            return OkResponse()
        await self.require_agent_access(agent=agent, ctx=ctx, write=True)

        gateway: Gateway | None = None
        client_config: GatewayClientConfig | None = None
        workspace_path: str | None = None

        if agent.board_id is None:
            # Gateway-main agents are not tied to a board; resolve via agent.gateway_id.
            gateway = await Gateway.objects.by_id(agent.gateway_id).first(self.session)
            client_config = optional_gateway_client_config(gateway)
            if gateway is not None and client_config is not None:
                try:
                    workspace_path = await OpenClawGatewayProvisioner().delete_agent_lifecycle(
                        agent=agent,
                        gateway=gateway,
                    )
                except OpenClawGatewayError as exc:
                    self.record_instruction_failure(self.session, agent, str(exc), "delete")
                    await self.session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Gateway cleanup failed: {exc}",
                    ) from exc
                except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
                    self.record_instruction_failure(self.session, agent, str(exc), "delete")
                    await self.session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Workspace cleanup failed: {exc}",
                    ) from exc
        else:
            board = await self.require_board(str(agent.board_id))
            gateway, client_config = await self.require_gateway(board)
            try:
                workspace_path = await OpenClawGatewayProvisioner().delete_agent_lifecycle(
                    agent=agent,
                    gateway=gateway,
                )
            except OpenClawGatewayError as exc:
                self.record_instruction_failure(self.session, agent, str(exc), "delete")
                await self.session.commit()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway cleanup failed: {exc}",
                ) from exc
            except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
                self.record_instruction_failure(self.session, agent, str(exc), "delete")
                await self.session.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Workspace cleanup failed: {exc}",
                ) from exc

        record_activity(
            self.session,
            event_type="agent.delete.direct",
            message=f"Deleted agent {agent.name}.",
            agent_id=None,
        )
        now = utcnow()
        await crud.update_where(
            self.session,
            Task,
            col(Task.assigned_agent_id) == agent.id,
            col(Task.status) == "in_progress",
            assigned_agent_id=None,
            status="inbox",
            in_progress_at=None,
            updated_at=now,
            commit=False,
        )
        await crud.update_where(
            self.session,
            Task,
            col(Task.assigned_agent_id) == agent.id,
            col(Task.status) != "in_progress",
            assigned_agent_id=None,
            updated_at=now,
            commit=False,
        )
        await crud.update_where(
            self.session,
            ActivityEvent,
            col(ActivityEvent.agent_id) == agent.id,
            agent_id=None,
            commit=False,
        )
        await self.session.delete(agent)
        await self.session.commit()

        try:
            # Notify the gateway-main agent about cleanup for board-scoped deletes.
            # Skip when deleting the gateway-main agent itself.
            if gateway is None or client_config is None or agent.board_id is None:
                raise ValueError("skip main agent cleanup notification")
            main_session = GatewayAgentIdentity.session_key(gateway)
            if main_session and workspace_path:
                cleanup_message = (
                    "Cleanup request for deleted agent.\n\n"
                    f"Agent name: {agent.name}\n"
                    f"Agent id: {agent.id}\n"
                    f"Workspace path: {workspace_path}\n\n"
                    "Actions:\n"
                    "1) Remove the workspace directory.\n"
                    "2) Reply NO_REPLY.\n"
                )
                await ensure_session(main_session, config=client_config, label="Gateway Agent")
                await send_message(
                    cleanup_message,
                    session_key=main_session,
                    config=client_config,
                    deliver=False,
                )
        except (OSError, OpenClawGatewayError, ValueError):
            pass
        self.logger.info("agent.delete.success agent_id=%s", agent_id)
        return OkResponse()
