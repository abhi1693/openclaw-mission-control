"""Gateway session query service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status

from app.core.logging import TRACE_LEVEL
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.gateway_api import (
    GatewayEvalApprovalResolveRequest,
    GatewayEvalSessionEnsureRequest,
    GatewayResolveQuery,
    GatewaySessionHistoryResponse,
    GatewaySessionMessageRequest,
    GatewaySessionResponse,
    GatewaySessionsResponse,
    GatewaysStatusResponse,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.error_messages import normalize_gateway_error_message
from app.services.openclaw.gateway_compat import check_gateway_version_compatibility
from app.services.openclaw.gateway_resolver import gateway_client_config, require_gateway_for_board
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    delete_session,
    ensure_session,
    get_chat_history,
    openclaw_call,
    send_message,
    steer_session,
)
from app.services.openclaw.internal.agent_key import agent_key
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
    lead_only: bool
    reset_sessions: bool
    rotate_tokens: bool
    force_bootstrap: bool
    overwrite: bool
    board_id: UUID | None


class GatewaySessionService(OpenClawDBService):
    """Read/query gateway runtime session state for user-facing APIs."""

    _EXEC_APPROVAL_ID_RE = re.compile(
        r"Approval required \(id [^,]+, full ([0-9a-fA-F-]{36})\)",
    )

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _require_eval_session_id(session_id: str) -> str:
        normalized = session_id.strip()
        if normalized.startswith("eval-"):
            return normalized
        if ":eval-" in normalized:
            return normalized
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Eval session id must start with `eval-`.",
        )

    async def _resolve_eval_agent_gateway_id(self, *, board: Board, agent_id: str) -> str:
        agent = await Agent.objects.by_id(agent_id).first(self.session)
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )
        if agent.board_id != board.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Agent does not belong to the requested board.",
            )
        return agent_key(agent)

    @staticmethod
    def _eval_gateway_config(config: GatewayClientConfig) -> GatewayClientConfig:
        """Use backend/device connect mode for isolated eval sessions.

        Eval traffic is operator-driven but should not inherit control-ui/webchat
        initiating-surface restrictions, otherwise session-level exec overrides
        such as `/elevated full` are rejected before the role can do any work.
        """

        if not config.disable_device_pairing:
            return config
        return replace(config, disable_device_pairing=False)

    @staticmethod
    def to_resolve_query(
        board_id: str | None,
        gateway_url: str | None,
        gateway_token: str | None,
        gateway_disable_device_pairing: bool | None = None,
        gateway_allow_insecure_tls: bool | None = None,
    ) -> GatewayResolveQuery:
        return GatewayResolveQuery(
            board_id=board_id,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            gateway_disable_device_pairing=gateway_disable_device_pairing,
            gateway_allow_insecure_tls=gateway_allow_insecure_tls,
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

    @staticmethod
    def history_message_text(message: dict[str, object]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(part.strip() for part in parts if part.strip()).strip()
        return ""

    @classmethod
    def _history_contains_exec_approval(cls, history: list[object], approval_id: str) -> bool:
        normalized = approval_id.strip().lower()
        if not normalized:
            return False
        for item in history:
            if not isinstance(item, dict):
                continue
            text = cls.history_message_text(item)
            for match in cls._EXEC_APPROVAL_ID_RE.finditer(text):
                if match.group(1).strip().lower() == normalized:
                    return True
        return False

    async def resolve_gateway(
        self,
        params: GatewayResolveQuery,
        *,
        user: User | None = None,
        organization_id: UUID | None = None,
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
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="board_id or gateway_url is required",
                )
            token = (params.gateway_token or "").strip() or None
            gateway: Gateway | None = None
            can_query_saved_gateway = organization_id is not None and hasattr(self.session, "exec")
            if can_query_saved_gateway and (
                params.gateway_allow_insecure_tls is None
                or params.gateway_disable_device_pairing is None
            ):
                gateway_query = Gateway.objects.filter_by(url=raw_url)
                if organization_id is not None:
                    gateway_query = gateway_query.filter_by(organization_id=organization_id)
                gateway = await gateway_query.first(self.session)
            allow_insecure_tls = (
                params.gateway_allow_insecure_tls
                if params.gateway_allow_insecure_tls is not None
                else (gateway.allow_insecure_tls if gateway is not None else False)
            )
            disable_device_pairing = (
                params.gateway_disable_device_pairing
                if params.gateway_disable_device_pairing is not None
                else (gateway.disable_device_pairing if gateway is not None else False)
            )
            return (
                None,
                GatewayClientConfig(
                    url=raw_url,
                    token=token,
                    allow_insecure_tls=allow_insecure_tls,
                    disable_device_pairing=disable_device_pairing,
                ),
                None,
            )
        if not params.board_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
        board, config, main_session = await self.resolve_gateway(
            params,
            user=user,
            organization_id=organization_id,
        )
        self._require_same_org(board, organization_id)
        try:
            compatibility = await check_gateway_version_compatibility(config)
        except OpenClawGatewayError as exc:
            return GatewaysStatusResponse(
                connected=False,
                gateway_url=config.url,
                error=normalize_gateway_error_message(str(exc)),
            )
        if not compatibility.compatible:
            return GatewaysStatusResponse(
                connected=False,
                gateway_url=config.url,
                error=compatibility.message,
            )
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
                error=normalize_gateway_error_message(str(exc)),
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
        organization_id: UUID,
        user: User | None,
    ) -> None:
        board, config, main_session = await self.require_gateway(board_id, user=user)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        try:
            if payload.interrupt_if_active:
                # sessions.steer requires an existing live session; ensuring
                # one would create an empty session just to abort nothing,
                # plus the extra sessions.patch broadcast delays the
                # time-sensitive interrupt by one RTT.
                await steer_session(
                    payload.content,
                    session_key=session_id,
                    config=config,
                )
            else:
                if main_session and session_id == main_session:
                    await ensure_session(main_session, config=config, label="Gateway Agent")
                await send_message(
                    payload.content,
                    session_key=session_id,
                    config=config,
                )
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    async def ensure_eval_session(
        self,
        *,
        session_id: str,
        payload: GatewayEvalSessionEnsureRequest,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaySessionResponse:
        session_id = self._require_eval_session_id(session_id)
        board, config, _ = await self.require_gateway(board_id, user=user)
        config = self._eval_gateway_config(config)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        label = (payload.label or f"OpenClaw Eval Session {session_id}").strip()
        try:
            ensured: object
            resolved_session_key = session_id
            if payload.agent_id:
                agent_gateway_id = await self._resolve_eval_agent_gateway_id(
                    board=board,
                    agent_id=payload.agent_id,
                )
                ensured = await openclaw_call(
                    "sessions.create",
                    {
                        "key": session_id,
                        "agentId": agent_gateway_id,
                        "label": label,
                    },
                    config=config,
                )
                if isinstance(ensured, dict):
                    resolved_session_key = str(
                        ensured.get("key")
                        or (ensured.get("entry") or {}).get("key")
                        or session_id
                    ).strip() or session_id
            else:
                ensured = await ensure_session(session_id, config=config, label=label)
            if payload.reset:
                await openclaw_call("sessions.reset", {"key": resolved_session_key}, config=config)
                if not payload.agent_id:
                    ensured = await ensure_session(session_id, config=config, label=label)
                else:
                    ensured = {
                        "key": resolved_session_key,
                        "label": label,
                    }
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        if isinstance(ensured, dict):
            entry = ensured.get("entry") or ensured
        else:
            entry = {"key": session_id, "label": label}
        return GatewaySessionResponse(session=entry)

    async def get_eval_session_history(
        self,
        *,
        session_id: str,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> GatewaySessionHistoryResponse:
        session_id = self._require_eval_session_id(session_id)
        board, config, _ = await self.require_gateway(board_id, user=user)
        config = self._eval_gateway_config(config)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
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

    async def send_eval_session_message(
        self,
        *,
        session_id: str,
        payload: GatewaySessionMessageRequest,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> None:
        session_id = self._require_eval_session_id(session_id)
        board, config, _ = await self.require_gateway(board_id, user=user)
        config = self._eval_gateway_config(config)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        try:
            await send_message(
                payload.content,
                session_key=session_id,
                config=config,
                deliver=True,
            )
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    async def resolve_eval_session_exec_approval(
        self,
        *,
        session_id: str,
        payload: GatewayEvalApprovalResolveRequest,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> None:
        session_id = self._require_eval_session_id(session_id)
        board, config, _ = await self.require_gateway(board_id, user=user)
        eval_config = self._eval_gateway_config(config)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        approval_id = payload.approval_id.strip()
        decision = payload.decision.strip()
        try:
            history = await get_chat_history(session_id, config=eval_config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        history_items = (
            history["messages"]
            if isinstance(history, dict) and isinstance(history.get("messages"), list)
            else self.as_object_list(history)
        )
        if not self._history_contains_exec_approval(history_items, approval_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Approval id not present in eval session history.",
            )
        try:
            await openclaw_call(
                "exec.approval.resolve",
                {"id": approval_id, "decision": decision},
                config=config,
            )
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    async def delete_eval_session(
        self,
        *,
        session_id: str,
        board_id: str | None,
        organization_id: UUID,
        user: User | None,
    ) -> None:
        session_id = self._require_eval_session_id(session_id)
        board, config, _ = await self.require_gateway(board_id, user=user)
        config = self._eval_gateway_config(config)
        self._require_same_org(board, organization_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await require_board_access(self.session, user=user, board=board, write=True)
        try:
            await delete_session(session_id, config=config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
