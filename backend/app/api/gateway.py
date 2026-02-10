"""Thin gateway session-inspection API wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_org_admin
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.integrations.openclaw_gateway_protocol import (
    GATEWAY_EVENTS,
    GATEWAY_METHODS,
    PROTOCOL_VERSION,
)
from app.schemas.common import OkResponse
from app.schemas.gateway_api import (
    GatewayCommandsResponse,
    GatewayResolveQuery,
    GatewaySessionHistoryResponse,
    GatewaySessionMessageRequest,
    GatewaySessionResponse,
    GatewaySessionsResponse,
    GatewaysStatusResponse,
)
from app.services.openclaw import GatewaySessionService
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
) -> GatewayResolveQuery:
    return GatewaySessionService.to_resolve_query(
        board_id=board_id,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
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
) -> OkResponse:
    """Send a message into a specific gateway session."""
    service = GatewaySessionService(session)
    await service.send_session_message(
        session_id=session_id,
        payload=payload,
        board_id=board_id,
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
