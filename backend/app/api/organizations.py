from __future__ import annotations

import secrets
from typing import Any, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_org_admin, require_org_member
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.boards import Board
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.organization_invites import OrganizationInvite
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User
from app.schemas.organizations import (
    OrganizationActiveUpdate,
    OrganizationBoardAccessRead,
    OrganizationCreate,
    OrganizationInviteAccept,
    OrganizationInviteCreate,
    OrganizationInviteRead,
    OrganizationListItem,
    OrganizationMemberAccessUpdate,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
    OrganizationRead,
    OrganizationUserRead,
)
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.organizations import (
    OrganizationContext,
    accept_invite,
    apply_invite_board_access,
    apply_invite_to_member,
    apply_member_access_update,
    get_active_membership,
    get_member,
    is_org_admin,
    normalize_invited_email,
    normalize_role,
    set_active_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _member_to_read(member: OrganizationMember, user: User | None) -> OrganizationMemberRead:
    model = OrganizationMemberRead.model_validate(member, from_attributes=True)
    if user is not None:
        model.user = OrganizationUserRead.model_validate(user, from_attributes=True)
    return model


@router.post("", response_model=OrganizationRead)
async def create_organization(
    payload: OrganizationCreate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> OrganizationRead:
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    existing = (
        await session.exec(
            select(Organization).where(func.lower(col(Organization.name)) == name.lower())
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    now = utcnow()
    org = Organization(name=name, created_at=now, updated_at=now)
    session.add(org)
    await session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=auth.user.id,
        role="owner",
        all_boards_read=True,
        all_boards_write=True,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    await session.flush()
    await set_active_organization(session, user=auth.user, organization_id=org.id)
    await session.commit()
    await session.refresh(org)
    return OrganizationRead.model_validate(org, from_attributes=True)


@router.get("/me/list", response_model=list[OrganizationListItem])
async def list_my_organizations(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> list[OrganizationListItem]:
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    await get_active_membership(session, auth.user)
    db_user = await session.get(User, auth.user.id)
    active_id = db_user.active_organization_id if db_user else auth.user.active_organization_id

    statement = (
        select(Organization, OrganizationMember)
        .join(OrganizationMember, col(OrganizationMember.organization_id) == col(Organization.id))
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


@router.patch("/me/active", response_model=OrganizationRead)
async def set_active_org(
    payload: OrganizationActiveUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> OrganizationRead:
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await set_active_organization(
        session, user=auth.user, organization_id=payload.organization_id
    )
    organization = await session.get(Organization, member.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return OrganizationRead.model_validate(organization, from_attributes=True)


@router.get("/me", response_model=OrganizationRead)
async def get_my_org(ctx: OrganizationContext = Depends(require_org_member)) -> OrganizationRead:
    return OrganizationRead.model_validate(ctx.organization, from_attributes=True)


@router.get("/me/member", response_model=OrganizationMemberRead)
async def get_my_membership(
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> OrganizationMemberRead:
    user = await session.get(User, ctx.member.user_id)
    access_rows = list(
        await session.exec(
            select(OrganizationBoardAccess).where(
                col(OrganizationBoardAccess.organization_member_id) == ctx.member.id
            )
        )
    )
    model = _member_to_read(ctx.member, user)
    model.board_access = [
        OrganizationBoardAccessRead.model_validate(row, from_attributes=True)
        for row in access_rows
    ]
    return model


@router.get("/me/members", response_model=DefaultLimitOffsetPage[OrganizationMemberRead])
async def list_org_members(
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> DefaultLimitOffsetPage[OrganizationMemberRead]:
    statement = (
        select(OrganizationMember, User)
        .join(User, col(User.id) == col(OrganizationMember.user_id))
        .where(col(OrganizationMember.organization_id) == ctx.organization.id)
        .order_by(func.lower(col(User.email)).asc(), col(User.name).asc())
    )

    def _transform(items: Sequence[Any]) -> Sequence[Any]:
        output: list[OrganizationMemberRead] = []
        for member, user in items:
            output.append(_member_to_read(member, user))
        return output

    return await paginate(session, statement, transformer=_transform)


@router.get("/me/members/{member_id}", response_model=OrganizationMemberRead)
async def get_org_member(
    member_id: UUID,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> OrganizationMemberRead:
    member = await session.get(OrganizationMember, member_id)
    if member is None or member.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not is_org_admin(ctx.member) and member.user_id != ctx.member.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    user = await session.get(User, member.user_id)
    access_rows = list(
        await session.exec(
            select(OrganizationBoardAccess).where(
                col(OrganizationBoardAccess.organization_member_id) == member.id
            )
        )
    )
    model = _member_to_read(member, user)
    model.board_access = [
        OrganizationBoardAccessRead.model_validate(row, from_attributes=True)
        for row in access_rows
    ]
    return model


@router.patch("/me/members/{member_id}", response_model=OrganizationMemberRead)
async def update_org_member(
    member_id: UUID,
    payload: OrganizationMemberUpdate,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OrganizationMemberRead:
    member = await session.get(OrganizationMember, member_id)
    if member is None or member.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    if "role" in updates and updates["role"] is not None:
        member.role = normalize_role(updates["role"])
    member.updated_at = utcnow()
    session.add(member)
    await session.commit()
    await session.refresh(member)
    user = await session.get(User, member.user_id)
    return _member_to_read(member, user)


@router.put("/me/members/{member_id}/access", response_model=OrganizationMemberRead)
async def update_member_access(
    member_id: UUID,
    payload: OrganizationMemberAccessUpdate,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OrganizationMemberRead:
    member = await session.get(OrganizationMember, member_id)
    if member is None or member.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    board_ids = {entry.board_id for entry in payload.board_access}
    if board_ids:
        valid_board_ids = set(
            await session.exec(
                select(Board.id)
                .where(col(Board.id).in_(board_ids))
                .where(col(Board.organization_id) == ctx.organization.id)
            )
        )
        if valid_board_ids != board_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    await apply_member_access_update(session, member=member, update=payload)
    await session.commit()
    await session.refresh(member)
    user = await session.get(User, member.user_id)
    return _member_to_read(member, user)


@router.get("/me/invites", response_model=DefaultLimitOffsetPage[OrganizationInviteRead])
async def list_org_invites(
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> DefaultLimitOffsetPage[OrganizationInviteRead]:
    statement = (
        select(OrganizationInvite)
        .where(col(OrganizationInvite.organization_id) == ctx.organization.id)
        .where(col(OrganizationInvite.accepted_at).is_(None))
        .order_by(col(OrganizationInvite.created_at).desc())
    )
    return await paginate(session, statement)


@router.post("/me/invites", response_model=OrganizationInviteRead)
async def create_org_invite(
    payload: OrganizationInviteCreate,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OrganizationInviteRead:
    email = normalize_invited_email(payload.invited_email)
    if not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    existing_user = (
        await session.exec(select(User).where(func.lower(col(User.email)) == email))
    ).first()
    if existing_user is not None:
        existing_member = await get_member(
            session,
            user_id=existing_user.id,
            organization_id=ctx.organization.id,
        )
        if existing_member is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    token = secrets.token_urlsafe(24)
    invite = OrganizationInvite(
        organization_id=ctx.organization.id,
        invited_email=email,
        token=token,
        role=normalize_role(payload.role),
        all_boards_read=payload.all_boards_read,
        all_boards_write=payload.all_boards_write,
        created_by_user_id=ctx.member.user_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(invite)
    await session.flush()

    board_ids = {entry.board_id for entry in payload.board_access}
    if board_ids:
        valid_board_ids = set(
            await session.exec(
                select(Board.id)
                .where(col(Board.id).in_(board_ids))
                .where(col(Board.organization_id) == ctx.organization.id)
            )
        )
        if valid_board_ids != board_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    await apply_invite_board_access(session, invite=invite, entries=payload.board_access)
    await session.commit()
    await session.refresh(invite)
    return OrganizationInviteRead.model_validate(invite, from_attributes=True)


@router.delete("/me/invites/{invite_id}", response_model=OrganizationInviteRead)
async def revoke_org_invite(
    invite_id: UUID,
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_admin),
) -> OrganizationInviteRead:
    invite = await session.get(OrganizationInvite, invite_id)
    if invite is None or invite.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await session.execute(
        delete(OrganizationInviteBoardAccess).where(
            col(OrganizationInviteBoardAccess.organization_invite_id) == invite.id
        ),
    )
    await session.delete(invite)
    await session.commit()
    return OrganizationInviteRead.model_validate(invite, from_attributes=True)


@router.post("/invites/accept", response_model=OrganizationMemberRead)
async def accept_org_invite(
    payload: OrganizationInviteAccept,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> OrganizationMemberRead:
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    invite = (
        await session.exec(
            select(OrganizationInvite)
            .where(col(OrganizationInvite.token) == payload.token)
            .where(col(OrganizationInvite.accepted_at).is_(None))
        )
    ).first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if invite.invited_email and auth.user.email:
        if normalize_invited_email(invite.invited_email) != normalize_invited_email(
            auth.user.email
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    existing = await get_member(
        session,
        user_id=auth.user.id,
        organization_id=invite.organization_id,
    )
    if existing is None:
        member = await accept_invite(session, invite, auth.user)
    else:
        await apply_invite_to_member(session, member=existing, invite=invite)
        invite.accepted_by_user_id = auth.user.id
        invite.accepted_at = utcnow()
        invite.updated_at = utcnow()
        session.add(invite)
        await session.commit()
        member = existing

    user = await session.get(User, member.user_id)
    return _member_to_read(member, user)
