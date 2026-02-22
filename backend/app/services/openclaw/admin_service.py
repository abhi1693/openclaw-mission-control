"""Gateway admin lifecycle service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col

from app.core.auth import AuthContext
from app.core.logging import TRACE_LEVEL
from app.core.time import utcnow
from app.db import crud
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_webhooks import BoardWebhook
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.schemas.gateways import GatewayTemplatesSyncResult
from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG
from app.services.openclaw.db_agent_state import (
    mark_provision_complete,
    mark_provision_requested,
    mint_agent_token,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_compat import check_gateway_runtime_compatibility
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError, openclaw_call
from app.services.openclaw.provisioning import OpenClawGatewayProvisioner
from app.services.openclaw.provisioning_db import (
    GatewayTemplateSyncOptions,
    OpenClawProvisioningService,
)
from app.services.openclaw.session_service import GatewayTemplateSyncQuery
from app.services.openclaw.shared import GatewayAgentIdentity
from app.services.organizations import get_org_owner_user

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


class AbstractGatewayMainAgentManager(ABC):
    """Abstract manager for gateway-main agent naming/profile behavior."""

    @abstractmethod
    def build_main_agent_name(self, gateway: Gateway) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_identity_profile(self) -> dict[str, str]:
        raise NotImplementedError


class DefaultGatewayMainAgentManager(AbstractGatewayMainAgentManager):
    """Default naming/profile strategy for gateway-main agents."""

    def build_main_agent_name(self, gateway: Gateway) -> str:
        return f"{gateway.name} Gateway Agent"

    def build_identity_profile(self) -> dict[str, str]:
        return {
            "role": "Gateway Agent",
            "communication_style": "direct, concise, practical",
            "emoji": ":compass:",
        }


class GatewayAdminLifecycleService(OpenClawDBService):
    """Write-side gateway lifecycle service (CRUD, main agent, template sync)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        main_agent_manager: AbstractGatewayMainAgentManager | None = None,
    ) -> None:
        super().__init__(session)
        self._main_agent_manager = main_agent_manager or DefaultGatewayMainAgentManager()

    @property
    def main_agent_manager(self) -> AbstractGatewayMainAgentManager:
        return self._main_agent_manager

    @main_agent_manager.setter
    def main_agent_manager(self, value: AbstractGatewayMainAgentManager) -> None:
        self._main_agent_manager = value

    async def require_gateway(
        self,
        *,
        gateway_id: UUID,
        organization_id: UUID,
    ) -> Gateway:
        gateway = (
            await Gateway.objects.by_id(gateway_id)
            .filter(col(Gateway.organization_id) == organization_id)
            .first(self.session)
        )
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gateway not found",
            )
        return gateway

    async def find_main_agent(self, gateway: Gateway) -> Agent | None:
        return (
            await Agent.objects.filter_by(gateway_id=gateway.id)
            .filter(col(Agent.board_id).is_(None))
            .first(self.session)
        )

    async def upsert_main_agent_record(self, gateway: Gateway) -> tuple[Agent, bool]:
        changed = False
        session_key = GatewayAgentIdentity.session_key(gateway)
        agent = await self.find_main_agent(gateway)
        main_agent_name = self.main_agent_manager.build_main_agent_name(gateway)
        identity_profile = self.main_agent_manager.build_identity_profile()
        if agent is None:
            agent = Agent(
                name=main_agent_name,
                status="provisioning",
                board_id=None,
                gateway_id=gateway.id,
                is_board_lead=False,
                openclaw_session_id=session_key,
                heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
                identity_profile=identity_profile,
            )
            self.session.add(agent)
            changed = True
        if agent.board_id is not None:
            agent.board_id = None
            changed = True
        if agent.gateway_id != gateway.id:
            agent.gateway_id = gateway.id
            changed = True
        if agent.is_board_lead:
            agent.is_board_lead = False
            changed = True
        if agent.name != main_agent_name:
            agent.name = main_agent_name
            changed = True
        if agent.openclaw_session_id != session_key:
            agent.openclaw_session_id = session_key
            changed = True
        if agent.heartbeat_config is None:
            agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
            changed = True
        if agent.identity_profile is None:
            agent.identity_profile = identity_profile
            changed = True
        if not agent.status:
            agent.status = "provisioning"
            changed = True
        if changed:
            agent.updated_at = utcnow()
            self.session.add(agent)
        return agent, changed

    async def gateway_has_main_agent_entry(self, gateway: Gateway) -> bool:
        if not gateway.url:
            return False
        config = GatewayClientConfig(
            url=gateway.url, token=gateway.token, allow_insecure_tls=gateway.allow_insecure_tls
        )
        target_id = GatewayAgentIdentity.openclaw_agent_id(gateway)
        try:
            await openclaw_call("agents.files.list", {"agentId": target_id}, config=config)
        except OpenClawGatewayError as exc:
            message = str(exc).lower()
            if any(marker in message for marker in ("not found", "unknown agent", "no such agent")):
                return False
            return True
        return True

    async def assert_gateway_runtime_compatible(
        self, *, url: str, token: str | None, allow_insecure_tls: bool = False
    ) -> None:
        """Validate that a gateway runtime meets minimum supported version."""
        config = GatewayClientConfig(url=url, token=token, allow_insecure_tls=allow_insecure_tls)
        try:
            result = await check_gateway_runtime_compatibility(config)
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gateway compatibility check failed: {exc}",
            ) from exc
        if not result.compatible:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=result.message or "Gateway runtime version is not supported.",
            )

    async def provision_main_agent_record(
        self,
        gateway: Gateway,
        agent: Agent,
        *,
        user: User | None,
        action: str,
        notify: bool,
    ) -> Agent:
        template_user = user or await get_org_owner_user(
            self.session,
            organization_id=gateway.organization_id,
        )
        if template_user is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Organization owner not found (required for gateway agent USER.md rendering).",
            )
        raw_token = mint_agent_token(agent)
        mark_provision_requested(
            agent,
            action=action,
            status="updating" if action == "update" else "provisioning",
        )
        await self.add_commit_refresh(agent)
        if not gateway.url:
            return agent

        try:
            await OpenClawGatewayProvisioner().apply_agent_lifecycle(
                agent=agent,
                gateway=gateway,
                board=None,
                auth_token=raw_token,
                user=template_user,
                action=action,
                wake=notify,
                deliver_wakeup=True,
            )
        except OpenClawGatewayError as exc:
            self.logger.error(
                "gateway.main_agent.provision_failed_gateway gateway_id=%s agent_id=%s error=%s",
                gateway.id,
                agent.id,
                str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gateway {action} failed: {exc}",
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            self.logger.error(
                "gateway.main_agent.provision_failed gateway_id=%s agent_id=%s error=%s",
                gateway.id,
                agent.id,
                str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error {action}ing gateway provisioning.",
            ) from exc

        mark_provision_complete(agent, status="online")
        await self.add_commit_refresh(agent)

        self.logger.info(
            "gateway.main_agent.provision_success gateway_id=%s agent_id=%s action=%s",
            gateway.id,
            agent.id,
            action,
        )
        return agent

    async def ensure_main_agent(
        self,
        gateway: Gateway,
        auth: AuthContext,
        *,
        action: str = "provision",
    ) -> Agent:
        self.logger.log(
            TRACE_LEVEL,
            "gateway.main_agent.ensure.start gateway_id=%s action=%s",
            gateway.id,
            action,
        )
        agent, _ = await self.upsert_main_agent_record(gateway)
        return await self.provision_main_agent_record(
            gateway,
            agent,
            user=auth.user,
            action=action,
            notify=True,
        )

    async def ensure_gateway_agents_exist(self, gateways: list[Gateway]) -> None:
        for gateway in gateways:
            agent, gateway_changed = await self.upsert_main_agent_record(gateway)
            has_gateway_entry = await self.gateway_has_main_agent_entry(gateway)
            needs_provision = (
                gateway_changed or not bool(agent.agent_token_hash) or not has_gateway_entry
            )
            if needs_provision:
                await self.provision_main_agent_record(
                    gateway,
                    agent,
                    user=None,
                    action="provision",
                    notify=False,
                )

    async def clear_agent_foreign_keys(self, *, agent_id: UUID) -> None:
        now = utcnow()
        await crud.update_where(
            self.session,
            Task,
            col(Task.assigned_agent_id) == agent_id,
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
            col(Task.assigned_agent_id) == agent_id,
            col(Task.status) != "in_progress",
            assigned_agent_id=None,
            updated_at=now,
            commit=False,
        )
        await crud.update_where(
            self.session,
            ActivityEvent,
            col(ActivityEvent.agent_id) == agent_id,
            agent_id=None,
            commit=False,
        )
        await crud.update_where(
            self.session,
            Approval,
            col(Approval.agent_id) == agent_id,
            agent_id=None,
            commit=False,
        )
        await crud.update_where(
            self.session,
            BoardWebhook,
            col(BoardWebhook.agent_id) == agent_id,
            agent_id=None,
            updated_at=now,
            commit=False,
        )

    async def sync_templates(
        self,
        gateway: Gateway,
        *,
        query: GatewayTemplateSyncQuery,
        auth: AuthContext,
    ) -> GatewayTemplatesSyncResult:
        self.logger.log(
            TRACE_LEVEL,
            "gateway.templates.sync.start gateway_id=%s include_main=%s",
            gateway.id,
            query.include_main,
        )
        await self.ensure_gateway_agents_exist([gateway])
        result = await OpenClawProvisioningService(self.session).sync_gateway_templates(
            gateway,
            GatewayTemplateSyncOptions(
                user=auth.user,
                include_main=query.include_main,
                lead_only=query.lead_only,
                reset_sessions=query.reset_sessions,
                rotate_tokens=query.rotate_tokens,
                force_bootstrap=query.force_bootstrap,
                overwrite=query.overwrite,
                board_id=query.board_id,
            ),
        )
        self.logger.info("gateway.templates.sync.success gateway_id=%s", gateway.id)
        return result
