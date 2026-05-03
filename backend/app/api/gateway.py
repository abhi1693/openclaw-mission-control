"""Thin gateway session-inspection API wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import require_org_admin
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.schemas.common import OkResponse
from app.schemas.gateway_api import (
    GatewayCommandsResponse,
    GatewayEvalApprovalResolveRequest,
    GatewayEvalSessionEnsureRequest,
    OpenClawRuntimeStatusResponse,
    GatewayResolveQuery,
    GatewaySessionHistoryResponse,
    GatewaySessionMessageRequest,
    GatewaySessionResponse,
    GatewaySessionsResponse,
    GatewaysStatusResponse,
    ProjectedGatewaySession,
    ProjectedGatewaySessionsResponse,
)
from app.services.mc_gateway_subscriber.session_state_repo import (
    SessionStateRepo,
)
from app.services.openclaw.gateway_rpc import GATEWAY_EVENTS, GATEWAY_METHODS, PROTOCOL_VERSION
from app.services.openclaw.internal.agent_key import agent_key
from app.services.openclaw.runtime_status import collect_openclaw_status
from app.services.openclaw.session_service import GatewaySessionService
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/gateways", tags=["gateways"])
SESSION_DEP = Depends(get_session)
AUTH_DEP = Depends(get_auth_context)
ORG_ADMIN_DEP = Depends(require_org_admin)
BOARD_ID_QUERY = Query(default=None)


def _query_to_resolve_input(
    board_id: str | None = Query(default=None),
    gateway_url: str | None = Query(default=None),
    gateway_token: str | None = Query(default=None),
    gateway_disable_device_pairing: bool | None = Query(default=None),
    gateway_allow_insecure_tls: bool | None = Query(default=None),
) -> GatewayResolveQuery:
    return GatewaySessionService.to_resolve_query(
        board_id=board_id,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        gateway_disable_device_pairing=gateway_disable_device_pairing,
        gateway_allow_insecure_tls=gateway_allow_insecure_tls,
    )


RESOLVE_INPUT_DEP = Depends(_query_to_resolve_input)


@router.get("/status", response_model=GatewaysStatusResponse)
async def gateways_status(
    params: GatewayResolveQuery = RESOLVE_INPUT_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaysStatusResponse:
    """Return gateway connectivity and session status."""
    service = GatewaySessionService(session)
    return await service.get_status(
        params=params,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.get("/sessions", response_model=GatewaySessionsResponse)
async def list_gateway_sessions(
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionsResponse:
    """List sessions for a gateway associated with a board."""
    service = GatewaySessionService(session)
    return await service.get_sessions(
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.get("/sessions/{session_id}", response_model=GatewaySessionResponse)
async def get_gateway_session(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionResponse:
    """Get a specific gateway session by key."""
    service = GatewaySessionService(session)
    return await service.get_session(
        session_id=session_id,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.get("/sessions/{session_id}/history", response_model=GatewaySessionHistoryResponse)
async def get_session_history(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionHistoryResponse:
    """Fetch chat history for a gateway session."""
    service = GatewaySessionService(session)
    return await service.get_session_history(
        session_id=session_id,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.post("/sessions/{session_id}/message", response_model=OkResponse)
async def send_gateway_session_message(
    session_id: str,
    payload: GatewaySessionMessageRequest,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Send a message into a specific gateway session."""
    service = GatewaySessionService(session)
    await service.send_session_message(
        session_id=session_id,
        payload=payload,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )
    return OkResponse()


@router.post("/evals/sessions/{session_id}", response_model=GatewaySessionResponse)
async def ensure_eval_gateway_session(
    session_id: str,
    payload: GatewayEvalSessionEnsureRequest,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionResponse:
    """Create or reset an isolated eval session for a board gateway."""
    service = GatewaySessionService(session)
    return await service.ensure_eval_session(
        session_id=session_id,
        payload=payload,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.get("/evals/sessions/{session_id}/history", response_model=GatewaySessionHistoryResponse)
async def get_eval_gateway_session_history(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionHistoryResponse:
    """Fetch chat history for an isolated eval session."""
    service = GatewaySessionService(session)
    return await service.get_eval_session_history(
        session_id=session_id,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )


@router.post("/evals/sessions/{session_id}/message", response_model=OkResponse)
async def send_eval_gateway_session_message(
    session_id: str,
    payload: GatewaySessionMessageRequest,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Send a prompt into an isolated eval session."""
    service = GatewaySessionService(session)
    await service.send_eval_session_message(
        session_id=session_id,
        payload=payload,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )
    return OkResponse()


@router.post("/evals/sessions/{session_id}/approvals/resolve", response_model=OkResponse)
async def resolve_eval_gateway_session_approval(
    session_id: str,
    payload: GatewayEvalApprovalResolveRequest,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Resolve a pending exec approval inside an isolated eval session."""
    service = GatewaySessionService(session)
    await service.resolve_eval_session_exec_approval(
        session_id=session_id,
        payload=payload,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )
    return OkResponse()


@router.delete("/evals/sessions/{session_id}", response_model=OkResponse)
async def delete_eval_gateway_session(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete an isolated eval session."""
    service = GatewaySessionService(session)
    await service.delete_eval_session(
        session_id=session_id,
        board_id=board_id,
        organization_id=ctx.organization.id,
        user=auth.user,
    )
    return OkResponse()


@router.get("/commands", response_model=GatewayCommandsResponse)
async def gateway_commands(
    _auth: AuthContext = AUTH_DEP,
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewayCommandsResponse:
    """Return supported gateway protocol methods and events."""
    return GatewayCommandsResponse(
        protocol_version=PROTOCOL_VERSION,
        methods=GATEWAY_METHODS,
        events=GATEWAY_EVENTS,
    )


@router.get("/runtime/status", response_model=OpenClawRuntimeStatusResponse)
async def openclaw_runtime_status(
    _auth: AuthContext = AUTH_DEP,
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OpenClawRuntimeStatusResponse:
    """Return the local OpenClaw runtime status snapshot."""

    snapshot = await collect_openclaw_status()
    return OpenClawRuntimeStatusResponse(
        ok=snapshot.ok,
        status=snapshot.payload,
        error=snapshot.error,
        return_code=snapshot.return_code,
    )


@router.get(
    "/projected-sessions",
    response_model=ProjectedGatewaySessionsResponse,
)
async def projected_gateway_sessions(
    agent_id: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> ProjectedGatewaySessionsResponse:
    """Return projected gateway session state for the caller's
    organization. Scopes via the org's ``agents`` rows: a row appears
    only if its ``agent_id`` (e.g. ``mc-<uuid>``) matches the gateway
    identity of an agent in the caller's org. Optional ``agent_id``
    query param narrows further but cannot widen across orgs.

    Gateway-internal rows (``mc-gateway-*``) and lead-namespace rows
    (``lead-<board_id>``) are NOT returned by this endpoint — they
    have no per-agent organization binding and need a separate
    operator-internal scope to surface.
    """
    # Agents have no organization_id directly; scope via the gateway
    # they're paired against (Agent.gateway_id → Gateway.organization_id).
    stmt = (
        select(Agent)
        .join(Gateway, Gateway.id == Agent.gateway_id)
        .where(Gateway.organization_id == ctx.organization.id)
    )
    result = await session.exec(stmt)
    org_agents = list(result.scalars().all())
    org_gateway_ids = {agent_key(a) for a in org_agents}
    if agent_id is not None:
        org_gateway_ids = org_gateway_ids & {agent_id}
    rows = await SessionStateRepo.list_for_agent_ids(
        session, agent_ids=org_gateway_ids
    )
    return ProjectedGatewaySessionsResponse(
        sessions=[
            ProjectedGatewaySession.model_validate(row, from_attributes=True)
            for row in rows
        ],
    )
