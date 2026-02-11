"""Gateway session query service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status

from app.core.logging import TRACE_LEVEL
from app.models.boards import Board
from app.schemas.gateway_api import (
    GatewayResolveQuery,
    GatewaySessionHistoryResponse,
    GatewaySessionMessageRequest,
    GatewaySessionResponse,
    GatewaySessionsResponse,
    GatewaysStatusResponse,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_resolver import gateway_client_config, require_gateway_for_board
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    ensure_session,
    get_chat_history,
    openclaw_call,
    send_message,
)
from app.services.openclaw.policies import OpenClawAuthorizationPolicy
from app.services.openclaw.shared import GatewayAgentIdentity
from app.services.organizations import require_board_access

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


@dataclass(frozen=True, slots=True)
class GatewayTemplateSyncQuery:
    """Sync options parsed from query args for gateway template operations."""

    include_main: bool
    reset_sessions: bool
    rotate_tokens: bool
    force_bootstrap: bool
    board_id: UUID | None


class GatewaySessionService(OpenClawDBService):
    """Read/query gateway runtime session state for user-facing APIs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def to_resolve_query(
        board_id: str | None,
        gateway_url: str | None,
        gateway_token: str | None,
    ) -> GatewayResolveQuery:
        return GatewayResolveQuery(
            board_id=board_id,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
        )

    @staticmethod
    def as_object_list(value: object) -> list[object]:
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

    async def resolve_gateway(
        self,
        params: GatewayResolveQuery,
        *,
        user: User | None = None,
    ) -> tuple[Board | None, GatewayClientConfig, str | None]:
        self.logger.log(
            TRACE_LEVEL,
            "gateway.resolve.start board_id=%s gateway_url=%s",
            params.board_id,
            params.gateway_url,
        )
        if params.gateway_url:
            raw_url = params.gateway_url.strip()
            if not raw_url:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="board_id or gateway_url is required",
                )
            return (
                None,
                GatewayClientConfig(
                    url=raw_url,
                    token=(params.gateway_token or "").strip() or None,
                ),
                None,
            )
        if not params.board_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="board_id or gateway_url is required",
            )
        board = await Board.objects.by_id(params.board_id).first(self.session)
        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Board not found",
            )
        if user is not None:
            await require_board_access(self.session, user=user, board=board, write=False)
        gateway = await require_gateway_for_board(self.session, board)
        config = gateway_client_config(gateway)
        main_session = GatewayAgentIdentity.session_key(gateway)
        return (
            board,
            config,
            main_session,
        )

    async def require_gateway(
        self,
        board_id: str | None,
        *,
        user: User | None = None,
    ) -> tuple[Board, GatewayClientConfig, str | None]:
        params = GatewayResolveQuery(board_id=board_id)
        board, config, main_session = await self.resolve_gateway(params, user=user)
        if board is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="board_id is required",
            )
        return board, config, main_session

    async def list_sessions(self, config: GatewayClientConfig) -> list[dict[str, object]]:
        sessions = await openclaw_call("sessions.list", config=config)
        if isinstance(sessions, dict):
            raw_items = self.as_object_list(sessions.get("sessions"))
        else:
            raw_items = self.as_object_list(sessions)
        return [item for item in raw_items if isinstance(item, dict)]

    async def with_main_session(
        self,
        sessions_list: list[dict[str, object]],
        *,
        config: GatewayClientConfig,
        main_session: str | None,
    ) -> list[dict[str, object]]:
        if not main_session or any(item.get("key") == main_session for item in sessions_list):
            return sessions_list
        try:
            await ensure_session(main_session, config=config, label="Gateway Agent")
            return await self.list_sessions(config)
        except OpenClawGatewayError:
            return sessions_list

    @staticmethod
    def _require_same_org(board: Board | None, organization_id: UUID) -> None:
        if board is None:
            return
        OpenClawAuthorizationPolicy.require_board_write_access(
            allowed=board.organization_id == organization_id,
        )

    async def get_status(
        self,
        *,
        params: GatewayResolveQuery,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaysStatusResponse:
        board, config, main_session = await self.resolve_gateway(params, user=user)
        self._require_same_org(board, organization_id)
        try:
            sessions = await openclaw_call("sessions.list", config=config)
            if isinstance(sessions, dict):
                sessions_list = self.as_object_list(sessions.get("sessions"))
            else:
                sessions_list = self.as_object_list(sessions)
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
                main_session=main_session_entry,
                main_session_error=main_session_error,
            )
        except OpenClawGatewayError as exc:
            return GatewaysStatusResponse(
                connected=False,
                gateway_url=config.url,
                error=str(exc),
            )

    async def get_sessions(
        self,
        *,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaySessionsResponse:
        params = GatewayResolveQuery(board_id=board_id)
        board, config, main_session = await self.resolve_gateway(params, user=user)
        self._require_same_org(board, organization_id)
        try:
            sessions = await openclaw_call("sessions.list", config=config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        if isinstance(sessions, dict):
            sessions_list = self.as_object_list(sessions.get("sessions"))
        else:
            sessions_list = self.as_object_list(sessions)

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
        return GatewaySessionsResponse(sessions=sessions_list, main_session=main_session_entry)

    async def get_session(
        self,
        *,
        session_id: str,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaySessionResponse:
        params = GatewayResolveQuery(board_id=board_id)
        board, config, main_session = await self.resolve_gateway(params, user=user)
        self._require_same_org(board, organization_id)
        try:
            sessions_list = await self.list_sessions(config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        sessions_list = await self.with_main_session(
            sessions_list,
            config=config,
            main_session=main_session,
        )
        session_entry = next(
            (item for item in sessions_list if item.get("key") == session_id), None
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

    async def get_session_history(
        self,
        *,
        session_id: str,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaySessionHistoryResponse:
        board, config, _ = await self.require_gateway(board_id, user=user)
        self._require_same_org(board, organization_id)
        try:
            history = await get_chat_history(session_id, config=config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        if isinstance(history, dict) and isinstance(history.get("messages"), list):
            return GatewaySessionHistoryResponse(history=history["messages"])
        return GatewaySessionHistoryResponse(history=self.as_object_list(history))

    async def send_session_message(
        self,
        *,
        session_id: str,
        payload: GatewaySessionMessageRequest,
        board_id: str | None,
        user: User | None,
    ) -> None:
        board, config, main_session = await self.require_gateway(board_id, user=user)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        try:
            if main_session and session_id == main_session:
                await ensure_session(main_session, config=config, label="Gateway Agent")
            await send_message(payload.content, session_key=session_id, config=config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
