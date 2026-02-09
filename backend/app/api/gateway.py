"""Gateway inspection and session-management endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_org_admin
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import (
    OpenClawGatewayError,
    ensure_session,
    get_chat_history,
    openclaw_call,
    send_message,
)
from app.integrations.openclaw_gateway_protocol import (
    GATEWAY_EVENTS,
    GATEWAY_METHODS,
    PROTOCOL_VERSION,
)
from app.models.boards import Board
from app.models.gateways import Gateway
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
from app.services.gateway_agents import gateway_agent_session_key
from app.services.organizations import OrganizationContext, require_board_access

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User

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
    return GatewayResolveQuery(
        board_id=board_id,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
    )


RESOLVE_INPUT_DEP = Depends(_query_to_resolve_input)


def _as_object_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return []
    if isinstance(value, Iterable):
        return list(value)
    return []


async def _resolve_gateway(
    session: AsyncSession,
    params: GatewayResolveQuery,
    *,
    user: User | None = None,
) -> tuple[Board | None, GatewayClientConfig, str | None]:
    if params.gateway_url:
        return (
            None,
            GatewayClientConfig(url=params.gateway_url, token=params.gateway_token),
            None,
        )
    if not params.board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_id or gateway_url is required",
        )
    board = await Board.objects.by_id(params.board_id).first(session)
    if board is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Board not found",
        )
    if user is not None:
        await require_board_access(session, user=user, board=board, write=False)
    if not board.gateway_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is required",
        )
    gateway = await Gateway.objects.by_id(board.gateway_id).first(session)
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Board gateway_id is invalid",
        )
    if not gateway.url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gateway url is required",
        )
    return (
        board,
        GatewayClientConfig(url=gateway.url, token=gateway.token),
        gateway_agent_session_key(gateway),
    )


async def _require_gateway(
    session: AsyncSession,
    board_id: str | None,
    *,
    user: User | None = None,
) -> tuple[Board, GatewayClientConfig, str | None]:
    params = GatewayResolveQuery(board_id=board_id)
    board, config, main_session = await _resolve_gateway(
        session,
        params,
        user=user,
    )
    if board is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="board_id is required",
        )
    return board, config, main_session


@router.get("/status", response_model=GatewaysStatusResponse)
async def gateways_status(
    params: GatewayResolveQuery = RESOLVE_INPUT_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaysStatusResponse:
    """Return gateway connectivity and session status."""
    board, config, main_session = await _resolve_gateway(
        session,
        params,
        user=auth.user,
    )
    if board is not None and board.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        sessions = await openclaw_call("sessions.list", config=config)
        if isinstance(sessions, dict):
            sessions_list = _as_object_list(sessions.get("sessions"))
        else:
            sessions_list = _as_object_list(sessions)
        main_session_entry: object | None = None
        main_session_error: str | None = None
        if main_session:
            try:
                ensured = await ensure_session(
                    main_session,
                    config=config,
                    label="Gateway Agent",
                )
                if isinstance(ensured, dict):
                    main_session_entry = ensured.get("entry") or ensured
            except OpenClawGatewayError as exc:
                main_session_error = str(exc)
        return GatewaysStatusResponse(
            connected=True,
            gateway_url=config.url,
            sessions_count=len(sessions_list),
            sessions=sessions_list,
            main_session_key=main_session,
            main_session=main_session_entry,
            main_session_error=main_session_error,
        )
    except OpenClawGatewayError as exc:
        return GatewaysStatusResponse(
            connected=False,
            gateway_url=config.url,
            error=str(exc),
        )


@router.get("/sessions", response_model=GatewaySessionsResponse)
async def list_gateway_sessions(
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionsResponse:
    """List sessions for a gateway associated with a board."""
    params = GatewayResolveQuery(board_id=board_id)
    board, config, main_session = await _resolve_gateway(
        session,
        params,
        user=auth.user,
    )
    if board is not None and board.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        sessions = await openclaw_call("sessions.list", config=config)
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if isinstance(sessions, dict):
        sessions_list = _as_object_list(sessions.get("sessions"))
    else:
        sessions_list = _as_object_list(sessions)

    main_session_entry: object | None = None
    if main_session:
        try:
            ensured = await ensure_session(
                main_session,
                config=config,
                label="Gateway Agent",
            )
            if isinstance(ensured, dict):
                main_session_entry = ensured.get("entry") or ensured
        except OpenClawGatewayError:
            main_session_entry = None

    return GatewaySessionsResponse(
        sessions=sessions_list,
        main_session_key=main_session,
        main_session=main_session_entry,
    )


async def _list_sessions(config: GatewayClientConfig) -> list[dict[str, object]]:
    sessions = await openclaw_call("sessions.list", config=config)
    if isinstance(sessions, dict):
        raw_items = _as_object_list(sessions.get("sessions"))
    else:
        raw_items = _as_object_list(sessions)
    return [item for item in raw_items if isinstance(item, dict)]


async def _with_main_session(
    sessions_list: list[dict[str, object]],
    *,
    config: GatewayClientConfig,
    main_session: str | None,
) -> list[dict[str, object]]:
    if not main_session or any(item.get("key") == main_session for item in sessions_list):
        return sessions_list
    try:
        await ensure_session(main_session, config=config, label="Gateway Agent")
        return await _list_sessions(config)
    except OpenClawGatewayError:
        return sessions_list


@router.get("/sessions/{session_id}", response_model=GatewaySessionResponse)
async def get_gateway_session(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionResponse:
    """Get a specific gateway session by key."""
    params = GatewayResolveQuery(board_id=board_id)
    board, config, main_session = await _resolve_gateway(
        session,
        params,
        user=auth.user,
    )
    if board is not None and board.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        sessions_list = await _list_sessions(config)
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    sessions_list = await _with_main_session(
        sessions_list,
        config=config,
        main_session=main_session,
    )
    session_entry = next(
        (item for item in sessions_list if item.get("key") == session_id),
        None,
    )
    if session_entry is None and main_session and session_id == main_session:
        try:
            ensured = await ensure_session(
                main_session,
                config=config,
                label="Gateway Agent",
            )
            if isinstance(ensured, dict):
                session_entry = ensured.get("entry") or ensured
        except OpenClawGatewayError:
            session_entry = None
    if session_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return GatewaySessionResponse(session=session_entry)


@router.get(
    "/sessions/{session_id}/history",
    response_model=GatewaySessionHistoryResponse,
)
async def get_session_history(
    session_id: str,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewaySessionHistoryResponse:
    """Fetch chat history for a gateway session."""
    board, config, _ = await _require_gateway(session, board_id, user=auth.user)
    if board.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        history = await get_chat_history(session_id, config=config)
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if isinstance(history, dict) and isinstance(history.get("messages"), list):
        return GatewaySessionHistoryResponse(history=history["messages"])
    return GatewaySessionHistoryResponse(history=_as_object_list(history))


@router.post("/sessions/{session_id}/message", response_model=OkResponse)
async def send_gateway_session_message(
    session_id: str,
    payload: GatewaySessionMessageRequest,
    board_id: str | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> OkResponse:
    """Send a message into a specific gateway session."""
    board, config, main_session = await _require_gateway(
        session,
        board_id,
        user=auth.user,
    )
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    try:
        if main_session and session_id == main_session:
            await ensure_session(main_session, config=config, label="Gateway Agent")
        await send_message(payload.content, session_key=session_id, config=config)
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
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
