"""Gateway CRUD and template synchronization endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col

from app.api.deps import require_org_admin
from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, ensure_session, send_message
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.schemas.common import OkResponse
from app.schemas.gateways import (
    GatewayCreate,
    GatewayRead,
    GatewayTemplatesSyncResult,
    GatewayUpdate,
)
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.agent_provisioning import (
    DEFAULT_HEARTBEAT_CONFIG,
    MainAgentProvisionRequest,
    ProvisionOptions,
    provision_main_agent,
)
from app.services.gateway_agents import gateway_agent_session_key, gateway_agent_session_key_for_id
from app.services.template_sync import GatewayTemplateSyncOptions
from app.services.template_sync import sync_gateway_templates as sync_gateway_templates_service

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

router = APIRouter(prefix="/gateways", tags=["gateways"])
SESSION_DEP = Depends(get_session)
AUTH_DEP = Depends(get_auth_context)
ORG_ADMIN_DEP = Depends(require_org_admin)
INCLUDE_MAIN_QUERY = Query(default=True)
RESET_SESSIONS_QUERY = Query(default=False)
ROTATE_TOKENS_QUERY = Query(default=False)
FORCE_BOOTSTRAP_QUERY = Query(default=False)
BOARD_ID_QUERY = Query(default=None)
_RUNTIME_TYPE_REFERENCES = (UUID,)


@dataclass(frozen=True)
class _TemplateSyncQuery:
    include_main: bool
    reset_sessions: bool
    rotate_tokens: bool
    force_bootstrap: bool
    board_id: UUID | None


def _template_sync_query(
    *,
    include_main: bool = INCLUDE_MAIN_QUERY,
    reset_sessions: bool = RESET_SESSIONS_QUERY,
    rotate_tokens: bool = ROTATE_TOKENS_QUERY,
    force_bootstrap: bool = FORCE_BOOTSTRAP_QUERY,
    board_id: UUID | None = BOARD_ID_QUERY,
) -> _TemplateSyncQuery:
    return _TemplateSyncQuery(
        include_main=include_main,
        reset_sessions=reset_sessions,
        rotate_tokens=rotate_tokens,
        force_bootstrap=force_bootstrap,
        board_id=board_id,
    )


SYNC_QUERY_DEP = Depends(_template_sync_query)


def _main_agent_name(gateway: Gateway) -> str:
    return f"{gateway.name} Gateway Agent"


async def _require_gateway(
    session: AsyncSession,
    *,
    gateway_id: UUID,
    organization_id: UUID,
) -> Gateway:
    gateway = (
        await Gateway.objects.by_id(gateway_id)
        .filter(col(Gateway.organization_id) == organization_id)
        .first(session)
    )
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gateway not found",
        )
    return gateway


async def _find_main_agent(
    session: AsyncSession,
    gateway: Gateway,
    previous_name: str | None = None,
    previous_session_key: str | None = None,
) -> Agent | None:
    preferred_session_key = gateway_agent_session_key(gateway)
    if preferred_session_key:
        agent = await Agent.objects.filter_by(
            openclaw_session_id=preferred_session_key,
        ).first(
            session,
        )
        if agent:
            return agent
    if gateway.main_session_key:
        agent = await Agent.objects.filter_by(
            openclaw_session_id=gateway.main_session_key,
        ).first(
            session,
        )
        if agent:
            return agent
    if previous_session_key:
        agent = await Agent.objects.filter_by(
            openclaw_session_id=previous_session_key,
        ).first(
            session,
        )
        if agent:
            return agent
    names = {_main_agent_name(gateway)}
    if previous_name:
        names.add(f"{previous_name} Main")
    for name in names:
        agent = await Agent.objects.filter_by(name=name).first(session)
        if agent:
            return agent
    return None


async def _ensure_main_agent(
    session: AsyncSession,
    gateway: Gateway,
    auth: AuthContext,
    *,
    previous: tuple[str | None, str | None] | None = None,
    action: str = "provision",
) -> Agent | None:
    if not gateway.url:
        return None
    session_key = gateway_agent_session_key(gateway)
    if gateway.main_session_key != session_key:
        gateway.main_session_key = session_key
        gateway.updated_at = utcnow()
        session.add(gateway)
    agent = await _find_main_agent(
        session,
        gateway,
        previous_name=previous[0] if previous else None,
        previous_session_key=previous[1] if previous else None,
    )
    if agent is None:
        agent = Agent(
            name=_main_agent_name(gateway),
            status="provisioning",
            board_id=None,
            is_board_lead=False,
            openclaw_session_id=session_key,
            heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
            identity_profile={
                "role": "Gateway Agent",
                "communication_style": "direct, concise, practical",
                "emoji": ":compass:",
            },
        )
        session.add(agent)
    agent.name = _main_agent_name(gateway)
    agent.openclaw_session_id = session_key
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    agent.provision_requested_at = utcnow()
    agent.provision_action = action
    agent.updated_at = utcnow()
    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    try:
        await provision_main_agent(
            agent,
            MainAgentProvisionRequest(
                gateway=gateway,
                auth_token=raw_token,
                user=auth.user,
                session_key=session_key,
                options=ProvisionOptions(action=action),
            ),
        )
        await ensure_session(
            session_key,
            config=GatewayClientConfig(url=gateway.url, token=gateway.token),
            label=agent.name,
        )
        await send_message(
            (
                f"Hello {agent.name}. Your gateway provisioning was updated.\n\n"
                "Please re-read AGENTS.md, USER.md, HEARTBEAT.md, and TOOLS.md. "
                "If BOOTSTRAP.md exists, run it once then delete it. "
                "Begin heartbeats after startup."
            ),
            session_key=session_key,
            config=GatewayClientConfig(url=gateway.url, token=gateway.token),
            deliver=True,
        )
    except OpenClawGatewayError:
        # Best-effort provisioning.
        pass
    return agent


@router.get("", response_model=DefaultLimitOffsetPage[GatewayRead])
async def list_gateways(
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> LimitOffsetPage[GatewayRead]:
    """List gateways for the caller's organization."""
    statement = (
        Gateway.objects.filter_by(organization_id=ctx.organization.id)
        .order_by(col(Gateway.created_at).desc())
        .statement
    )
    return await paginate(session, statement)


@router.post("", response_model=GatewayRead)
async def create_gateway(
    payload: GatewayCreate,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Gateway:
    """Create a gateway and provision or refresh its main agent."""
    data = payload.model_dump()
    gateway_id = uuid4()
    data["id"] = gateway_id
    data["organization_id"] = ctx.organization.id
    data["main_session_key"] = gateway_agent_session_key_for_id(gateway_id)
    gateway = await crud.create(session, Gateway, **data)
    await _ensure_main_agent(session, gateway, auth, action="provision")
    return gateway


@router.get("/{gateway_id}", response_model=GatewayRead)
async def get_gateway(
    gateway_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Gateway:
    """Return one gateway by id for the caller's organization."""
    return await _require_gateway(
        session,
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )


@router.patch("/{gateway_id}", response_model=GatewayRead)
async def update_gateway(
    gateway_id: UUID,
    payload: GatewayUpdate,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Gateway:
    """Patch a gateway and refresh the main-agent provisioning state."""
    gateway = await _require_gateway(
        session,
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    previous_name = gateway.name
    previous_session_key = gateway.main_session_key
    updates = payload.model_dump(exclude_unset=True)
    await crud.patch(session, gateway, updates)
    await _ensure_main_agent(
        session,
        gateway,
        auth,
        previous=(previous_name, previous_session_key),
        action="update",
    )
    return gateway


@router.post("/{gateway_id}/templates/sync", response_model=GatewayTemplatesSyncResult)
async def sync_gateway_templates(
    gateway_id: UUID,
    sync_query: _TemplateSyncQuery = SYNC_QUERY_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewayTemplatesSyncResult:
    """Sync templates for a gateway and optionally rotate runtime settings."""
    gateway = await _require_gateway(
        session,
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    return await sync_gateway_templates_service(
        session,
        gateway,
        GatewayTemplateSyncOptions(
            user=auth.user,
            include_main=sync_query.include_main,
            reset_sessions=sync_query.reset_sessions,
            rotate_tokens=sync_query.rotate_tokens,
            force_bootstrap=sync_query.force_bootstrap,
            board_id=sync_query.board_id,
        ),
    )


@router.delete("/{gateway_id}", response_model=OkResponse)
async def delete_gateway(
    gateway_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete a gateway in the caller's organization."""
    gateway = await _require_gateway(
        session,
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    await crud.delete(session, gateway)
    return OkResponse()
