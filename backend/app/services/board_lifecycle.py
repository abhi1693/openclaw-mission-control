"""Board lifecycle services.

This module contains DB-backed board workflows that may also interact with the
OpenClaw gateway. API routes should remain thin wrappers over these helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.db import crud
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.schemas.common import OkResponse
from app.services.openclaw.gateway_resolver import gateway_client_config, require_gateway_for_board
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.provisioning import OpenClawGatewayProvisioner

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board


async def delete_board(session: AsyncSession, *, board: Board) -> OkResponse:
    """Delete a board and all dependent records, cleaning gateway state when configured."""
    agents = await Agent.objects.filter_by(board_id=board.id).all(session)
    task_ids = list(await session.exec(select(Task.id).where(Task.board_id == board.id)))

    if board.gateway_id:
        gateway = await require_gateway_for_board(session, board, require_workspace_root=True)
        # Ensure URL is present (required for gateway cleanup calls).
        gateway_client_config(gateway)
        try:
            for agent in agents:
                await OpenClawGatewayProvisioner().delete_agent_lifecycle(
                    agent=agent,
                    gateway=gateway,
                )
        except OpenClawGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gateway cleanup failed: {exc}",
            ) from exc

    if task_ids:
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.task_id).in_(task_ids),
            commit=False,
        )
    await crud.delete_where(
        session,
        TaskDependency,
        col(TaskDependency.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.board_id) == board.id,
    )

    # Approvals can reference tasks and agents, so delete before both.
    approval_ids = select(Approval.id).where(col(Approval.board_id) == board.id)
    await crud.delete_where(
        session,
        ApprovalTaskLink,
        col(ApprovalTaskLink.approval_id).in_(approval_ids),
        commit=False,
    )
    await crud.delete_where(session, Approval, col(Approval.board_id) == board.id)

    await crud.delete_where(session, BoardMemory, col(BoardMemory.board_id) == board.id)
    await crud.delete_where(
        session,
        BoardOnboardingSession,
        col(BoardOnboardingSession.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.board_id) == board.id,
    )

    # Tasks reference agents and have dependent records.
    # Delete tasks before agents.
    await crud.delete_where(session, Task, col(Task.board_id) == board.id)

    if agents:
        agent_ids = [agent.id for agent in agents]
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.agent_id).in_(agent_ids),
            commit=False,
        )
        await crud.delete_where(session, Agent, col(Agent.id).in_(agent_ids))

    await session.delete(board)
    await session.commit()
    return OkResponse()
