"""OpenClaw authorization policy primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status

from app.services.openclaw.shared import GatewayAgentIdentity

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.boards import Board
    from app.models.gateways import Gateway


class OpenClawAuthorizationPolicy:
    """Centralized authz checks for OpenClaw lifecycle and coordination actions."""

    _GATEWAY_MAIN_ONLY_DETAIL = "Only the dedicated gateway agent may call this endpoint."

    @staticmethod
    def require_org_admin(*, is_admin: bool) -> None:
        if not is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    @staticmethod
    def require_same_agent_actor(
        *,
        actor_agent_id: UUID | None,
        target_agent_id: UUID,
    ) -> None:
        if actor_agent_id is not None and actor_agent_id != target_agent_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    @staticmethod
    def require_gateway_scoped_actor(*, actor_agent: Agent) -> None:
        if actor_agent.board_id is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    @classmethod
    def require_gateway_main_actor_binding(
        cls,
        *,
        actor_agent: Agent,
        gateway: Gateway | None,
    ) -> Gateway:
        cls.require_gateway_scoped_actor(actor_agent=actor_agent)
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=cls._GATEWAY_MAIN_ONLY_DETAIL,
            )
        if actor_agent.openclaw_session_id != GatewayAgentIdentity.session_key(gateway):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=cls._GATEWAY_MAIN_ONLY_DETAIL,
            )
        return gateway

    @staticmethod
    def require_gateway_configured(gateway: Gateway) -> None:
        if not gateway.url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Gateway url is required",
            )

    @staticmethod
    def require_gateway_in_org(
        *,
        gateway: Gateway | None,
        organization_id: UUID,
    ) -> Gateway:
        if gateway is None or gateway.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return gateway

    @staticmethod
    def require_board_in_org(
        *,
        board: Board | None,
        organization_id: UUID,
    ) -> Board:
        if board is None or board.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return board

    @staticmethod
    def require_board_in_gateway(
        *,
        board: Board | None,
        gateway: Gateway,
    ) -> Board:
        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Board not found",
            )
        if board.gateway_id != gateway.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board

    @staticmethod
    def require_board_agent_target(
        *,
        target: Agent | None,
        board: Board,
    ) -> Agent:
        if target is None or (target.board_id and target.board_id != board.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return target

    @staticmethod
    def require_board_write_access(*, allowed: bool) -> None:
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    @staticmethod
    def require_board_lead_actor(
        *,
        actor_agent: Agent | None,
        detail: str = "Only board leads can perform this action",
    ) -> Agent:
        if actor_agent is None or not actor_agent.is_board_lead:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )
        if not actor_agent.board_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board lead must be assigned to a board",
            )
        return actor_agent

    @staticmethod
    def require_board_lead_or_same_actor(
        *,
        actor_agent: Agent,
        target_agent_id: str,
    ) -> None:
        allowed = actor_agent.is_board_lead or str(actor_agent.id) == target_agent_id
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    @classmethod
    def resolve_board_lead_create_board_id(
        cls,
        *,
        actor_agent: Agent | None,
        requested_board_id: UUID | None,
    ) -> UUID:
        lead = cls.require_board_lead_actor(
            actor_agent=actor_agent,
            detail="Only board leads can create agents",
        )
        lead_board_id = lead.board_id
        if lead_board_id is None:
            msg = "Board lead must be assigned to a board"
            raise RuntimeError(msg)
        if requested_board_id and requested_board_id != lead_board_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board leads can only create agents in their own board",
            )
        return lead_board_id
