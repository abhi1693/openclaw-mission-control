"""Reusable FastAPI dependencies for auth and board/task access.

These dependencies are the main "policy wiring" layer for the API.

They:
- resolve the authenticated actor (human user vs agent)
- enforce organization/board access rules
- provide common "load or 404" helpers (board/task)

Why this exists:
- Keeping authorization logic centralized makes it easier to reason about (and
  audit) permissions as the API surface grows.
- Some routes allow either human users or agents; others require user auth.

If you're adding a new endpoint, prefer composing from these dependencies instead
of re-implementing permission checks in the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.core.agent_auth import AgentAuthContext, get_agent_auth_context_optional
from app.core.auth import AuthContext, get_auth_context, get_auth_context_optional
from app.db.session import get_session
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.admin_access import require_user_actor
from app.services.organizations import (
    OrganizationContext,
    ensure_member_for_user,
    get_active_membership,
    is_org_admin,
    require_board_access,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.agents import Agent
    from app.models.users import User

AUTH_DEP = Depends(get_auth_context)
AUTH_OPTIONAL_DEP = Depends(get_auth_context_optional)
AGENT_AUTH_OPTIONAL_DEP = Depends(get_agent_auth_context_optional)
SESSION_DEP = Depends(get_session)


def require_user_auth(auth: AuthContext = AUTH_DEP) -> AuthContext:
    """Require an authenticated human user (not an agent)."""
    require_user_actor(auth)
    return auth


@dataclass
class ActorContext:
    """Authenticated actor context for user or agent callers."""

    actor_type: Literal["user", "agent"]
    user: User | None = None
    agent: Agent | None = None


def require_user_or_agent(
    auth: AuthContext | None = AUTH_OPTIONAL_DEP,
    agent_auth: AgentAuthContext | None = AGENT_AUTH_OPTIONAL_DEP,
) -> ActorContext:
    """Authorize either a human user or an authenticated agent."""
    if auth is not None:
        require_user_actor(auth)
        return ActorContext(actor_type="user", user=auth.user)
    if agent_auth is not None:
        return ActorContext(actor_type="agent", agent=agent_auth.agent)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


ACTOR_DEP = Depends(require_user_or_agent)


async def require_org_member(
    auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OrganizationContext:
    """Resolve and require active organization membership for the current user."""
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await get_active_membership(session, auth.user)
    if member is None:
        member = await ensure_member_for_user(session, auth.user)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    organization = await Organization.objects.by_id(member.organization_id).first(
        session,
    )
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return OrganizationContext(organization=organization, member=member)


ORG_MEMBER_DEP = Depends(require_org_member)


async def require_org_admin(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationContext:
    """Require organization-admin membership privileges."""
    if not is_org_admin(ctx.member):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return ctx


async def get_board_or_404(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
) -> Board:
    """Load a board by id or raise HTTP 404."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return board


async def get_board_for_actor_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent and actor.agent.board_id and actor.agent.board_id != board.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=False)
    return board


async def get_board_for_actor_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent and actor.agent.board_id and actor.agent.board_id != board.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=True)
    return board


async def get_board_for_user_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=False)
    return board


async def get_board_for_user_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    return board


BOARD_READ_DEP = Depends(get_board_for_actor_read)


async def get_task_or_404(
    task_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Task:
    """Load a task for a board or raise HTTP 404."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None or task.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return task
