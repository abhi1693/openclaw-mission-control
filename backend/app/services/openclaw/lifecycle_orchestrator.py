"""Unified agent lifecycle orchestration.

This module centralizes DB-backed lifecycle transitions so call sites do not
duplicate provisioning/wake/state logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.core.time import utcnow
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.constants import CHECKIN_DEADLINE_AFTER_WAKE
from app.services.openclaw.db_agent_state import (
    mark_provision_complete,
    mark_provision_requested,
    mint_agent_token,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.lifecycle_queue import (
    QueuedAgentLifecycleReconcile,
    enqueue_lifecycle_reconcile,
)
from app.services.openclaw.provisioning import OpenClawGatewayProvisioner
from app.services.organizations import get_org_owner_user

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


class AgentLifecycleOrchestrator(OpenClawDBService):
    """Single lifecycle writer for agent provision/update transitions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _lock_agent(self, *, agent_id: UUID) -> Agent:
        statement = select(Agent).where(col(Agent.id) == agent_id).with_for_update()
        agent = (await self.session.exec(statement)).first()
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        return agent

    async def run_lifecycle(
        self,
        *,
        gateway: Gateway,
        agent_id: UUID,
        board: Board | None,
        user: User | None,
        action: str,
        auth_token: str | None = None,
        force_bootstrap: bool = False,
        reset_session: bool = False,
        wake: bool = True,
        deliver_wakeup: bool = True,
        wakeup_verb: str | None = None,
        clear_confirm_token: bool = False,
        raise_gateway_errors: bool = True,
    ) -> Agent:
        """Provision or update any agent under a per-agent lock."""

        locked = await self._lock_agent(agent_id=agent_id)
        template_user = user
        if board is None and template_user is None:
            template_user = await get_org_owner_user(
                self.session,
                organization_id=gateway.organization_id,
            )
            if template_user is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        "Organization owner not found "
                        "(required for gateway agent USER.md rendering)."
                    ),
                )

        raw_token = auth_token or mint_agent_token(locked)
        mark_provision_requested(
            locked,
            action=action,
            status="updating" if action == "update" else "provisioning",
        )
        locked.lifecycle_generation += 1
        locked.last_provision_error = None
        locked.checkin_deadline_at = utcnow() + CHECKIN_DEADLINE_AFTER_WAKE if wake else None
        if wake:
            locked.wake_attempts += 1
            locked.last_wake_sent_at = utcnow()
        self.session.add(locked)
        await self.session.flush()

        if not gateway.url:
            await self.session.commit()
            await self.session.refresh(locked)
            return locked

        try:
            await OpenClawGatewayProvisioner().apply_agent_lifecycle(
                agent=locked,
                gateway=gateway,
                board=board,
                auth_token=raw_token,
                user=template_user,
                action=action,
                force_bootstrap=force_bootstrap,
                reset_session=reset_session,
                wake=wake,
                deliver_wakeup=deliver_wakeup,
                wakeup_verb=wakeup_verb,
            )
        except OpenClawGatewayError as exc:
            locked.last_provision_error = str(exc)
            locked.updated_at = utcnow()
            self.session.add(locked)
            await self.session.commit()
            await self.session.refresh(locked)
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway {action} failed: {exc}",
                ) from exc
            return locked
        except (OSError, RuntimeError, ValueError) as exc:
            locked.last_provision_error = str(exc)
            locked.updated_at = utcnow()
            self.session.add(locked)
            await self.session.commit()
            await self.session.refresh(locked)
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Unexpected error {action}ing gateway provisioning.",
                ) from exc
            return locked

        mark_provision_complete(
            locked,
            status="online",
            clear_confirm_token=clear_confirm_token,
        )
        locked.last_provision_error = None
        locked.checkin_deadline_at = utcnow() + CHECKIN_DEADLINE_AFTER_WAKE if wake else None
        self.session.add(locked)
        await self.session.commit()
        await self.session.refresh(locked)
        if wake and locked.checkin_deadline_at is not None:
            enqueue_lifecycle_reconcile(
                QueuedAgentLifecycleReconcile(
                    agent_id=locked.id,
                    gateway_id=locked.gateway_id,
                    board_id=locked.board_id,
                    generation=locked.lifecycle_generation,
                    checkin_deadline_at=locked.checkin_deadline_at,
                )
            )
        return locked
