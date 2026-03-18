"""Organization management endpoints — simplified for single-user deployment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import require_org_member
from app.core.auth import get_auth_context
from app.db.session import get_session
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User
from app.schemas.organizations import (
    OrganizationListItem,
    OrganizationMemberRead,
    OrganizationRead,
    OrganizationUserRead,
)
from app.services.organizations import (
    OrganizationContext,
    get_active_membership,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/organizations", tags=["organizations"])
SESSION_DEP = Depends(get_session)
AUTH_DEP = Depends(get_auth_context)
ORG_MEMBER_DEP = Depends(require_org_member)


def _member_to_read(
    member: OrganizationMember,
    user: User | None,
) -> OrganizationMemberRead:
    model = OrganizationMemberRead.model_validate(member, from_attributes=True)
    if user is not None:
        model.user = OrganizationUserRead.model_validate(user, from_attributes=True)
    return model


@router.get("/me/list", response_model=list[OrganizationListItem])
async def list_my_organizations(
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> list[OrganizationListItem]:
    """List organizations where the current user is a member."""
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    await get_active_membership(session, auth.user)
    db_user = await User.objects.by_id(auth.user.id).first(session)
    active_id = db_user.active_organization_id if db_user else auth.user.active_organization_id

    statement = (
        select(Organization, OrganizationMember)
        .join(
            OrganizationMember,
            col(OrganizationMember.organization_id) == col(Organization.id),
        )
        .where(col(OrganizationMember.user_id) == auth.user.id)
        .order_by(func.lower(col(Organization.name)).asc())
    )
    rows = list(await session.exec(statement))
    return [
        OrganizationListItem(
            id=org.id,
            name=org.name,
            role=member.role,
            is_active=org.id == active_id,
        )
        for org, member in rows
    ]


@router.get("/me", response_model=OrganizationRead)
async def get_my_org(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationRead:
    """Return the caller's active organization."""
    return OrganizationRead.model_validate(ctx.organization, from_attributes=True)


@router.get("/me/member", response_model=OrganizationMemberRead)
async def get_my_membership(
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationMemberRead:
    """Get the caller's membership record in the active organization."""
    user = await User.objects.by_id(ctx.member.user_id).first(session)
    return _member_to_read(ctx.member, user)
