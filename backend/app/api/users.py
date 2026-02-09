"""User self-service API endpoints for profile retrieval and updates."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app.core.auth import AuthContext, delete_clerk_user, get_auth_context
from app.db import crud
from app.db.session import get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_group_memory import BoardGroupMemory
from app.models.board_groups import BoardGroup
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.organization_invites import OrganizationInvite
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.models.users import User
from app.schemas.common import OkResponse
from app.schemas.users import UserRead, UserUpdate

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/users", tags=["users"])
AUTH_CONTEXT_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


async def _delete_organization_tree(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> None:
    """Delete an organization and dependent rows without committing."""
    board_ids = select(Board.id).where(col(Board.organization_id) == organization_id)
    task_ids = select(Task.id).where(col(Task.board_id).in_(board_ids))
    agent_ids = select(Agent.id).where(col(Agent.board_id).in_(board_ids))
    member_ids = select(OrganizationMember.id).where(
        col(OrganizationMember.organization_id) == organization_id,
    )
    invite_ids = select(OrganizationInvite.id).where(
        col(OrganizationInvite.organization_id) == organization_id,
    )
    group_ids = select(BoardGroup.id).where(
        col(BoardGroup.organization_id) == organization_id,
    )

    await crud.delete_where(
        session,
        ActivityEvent,
        col(ActivityEvent.task_id).in_(task_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        ActivityEvent,
        col(ActivityEvent.agent_id).in_(agent_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskDependency,
        col(TaskDependency.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        Approval,
        col(Approval.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardMemory,
        col(BoardMemory.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardOnboardingSession,
        col(BoardOnboardingSession.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.organization_member_id).in_(member_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.organization_invite_id).in_(invite_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        Task,
        col(Task.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        Agent,
        col(Agent.board_id).in_(board_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        Board,
        col(Board.organization_id) == organization_id,
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardGroupMemory,
        col(BoardGroupMemory.board_group_id).in_(group_ids),
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardGroup,
        col(BoardGroup.organization_id) == organization_id,
        commit=False,
    )
    await crud.delete_where(
        session,
        Gateway,
        col(Gateway.organization_id) == organization_id,
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationInvite,
        col(OrganizationInvite.organization_id) == organization_id,
        commit=False,
    )
    await crud.delete_where(
        session,
        OrganizationMember,
        col(OrganizationMember.organization_id) == organization_id,
        commit=False,
    )
    await crud.update_where(
        session,
        User,
        col(User.active_organization_id) == organization_id,
        active_organization_id=None,
        commit=False,
    )
    await crud.delete_where(
        session,
        Organization,
        col(Organization.id) == organization_id,
        commit=False,
    )


@router.get("/me", response_model=UserRead)
async def get_me(auth: AuthContext = AUTH_CONTEXT_DEP) -> UserRead:
    """Return the authenticated user's current profile payload."""
    if auth.actor_type != "user" or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return UserRead.model_validate(auth.user)


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_CONTEXT_DEP,
) -> UserRead:
    """Apply partial profile updates for the authenticated user."""
    if auth.actor_type != "user" or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    updates = payload.model_dump(exclude_unset=True)
    user: User = auth.user
    for key, value in updates.items():
        setattr(user, key, value)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/me", response_model=OkResponse)
async def delete_me(
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_CONTEXT_DEP,
) -> OkResponse:
    """Delete the authenticated account and any personal-only organizations."""
    if auth.actor_type != "user" or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user: User = auth.user
    await delete_clerk_user(user.clerk_user_id)
    memberships = await OrganizationMember.objects.filter_by(user_id=user.id).all(session)

    await crud.update_where(
        session,
        OrganizationInvite,
        col(OrganizationInvite.created_by_user_id) == user.id,
        created_by_user_id=None,
        commit=False,
    )
    await crud.update_where(
        session,
        OrganizationInvite,
        col(OrganizationInvite.accepted_by_user_id) == user.id,
        accepted_by_user_id=None,
        commit=False,
    )
    await crud.update_where(
        session,
        Task,
        col(Task.created_by_user_id) == user.id,
        created_by_user_id=None,
        commit=False,
    )

    for member in memberships:
        org_members = await OrganizationMember.objects.filter_by(
            organization_id=member.organization_id,
        ).all(session)
        if len(org_members) <= 1:
            await _delete_organization_tree(
                session,
                organization_id=member.organization_id,
            )
            continue
        await crud.delete_where(
            session,
            OrganizationBoardAccess,
            col(OrganizationBoardAccess.organization_member_id) == member.id,
            commit=False,
        )
        await crud.delete_where(
            session,
            OrganizationMember,
            col(OrganizationMember.id) == member.id,
            commit=False,
        )

    await crud.delete_where(
        session,
        User,
        col(User.id) == user.id,
        commit=False,
    )
    await session.commit()
    return OkResponse()
