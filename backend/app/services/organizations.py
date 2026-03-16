"""Organization membership and board-access service helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.db import crud
from app.models.boards import Board
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.organization_invites import OrganizationInvite
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.skills import SkillPack
from app.models.users import User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.sql.elements import ColumnElement

    from app.schemas.organizations import (
        OrganizationBoardAccessSpec,
        OrganizationMemberAccessUpdate,
    )

DEFAULT_ORG_NAME = "Personal"


def _normalize_skill_pack_source_url(source_url: str) -> str:
    """Normalize pack source URL so duplicates with trivial formatting differences match."""
    normalized = str(source_url).strip().rstrip("/")
    if normalized.endswith(".git"):
        return normalized[: -len(".git")]
    return normalized


DEFAULT_INSTALLER_SKILL_PACKS = (
    (
        "sickn33/antigravity-awesome-skills",
        "antigravity-awesome-skills",
        "The Ultimate Collection of 800+ Agentic Skills for Claude Code/Antigravity/Cursor. "
        "Battle-tested, high-performance skills for AI agents including official skills from "
        "Anthropic and Vercel.",
    ),
    (
        "BrianRWagner/ai-marketing-skills",
        "ai-marketing-skills",
        "Marketing frameworks that AI actually executes. Use for Claude Code, OpenClaw, etc.",
    ),
)
ADMIN_ROLES = {"owner", "admin"}
ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}


@dataclass(frozen=True)
class OrganizationContext:
    """Resolved organization and membership for the active user."""

    organization: Organization
    member: OrganizationMember


def is_org_admin(member: OrganizationMember) -> bool:
    """Return whether a member has admin-level organization privileges."""
    return member.role in ADMIN_ROLES


async def get_member(
    session: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> OrganizationMember | None:
    """Fetch a membership by user id and organization id."""
    return await OrganizationMember.objects.filter_by(
        user_id=user_id,
        organization_id=organization_id,
    ).first(session)


async def get_org_owner_user(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> User | None:
    """Return the org owner User, if one exists."""
    owner = (
        await OrganizationMember.objects.filter_by(organization_id=organization_id)
        .filter(col(OrganizationMember.role) == "owner")
        .order_by(col(OrganizationMember.created_at).asc())
        .first(session)
    )
    if owner is None:
        return None
    return await User.objects.by_id(owner.user_id).first(session)


async def get_first_membership(
    session: AsyncSession,
    user_id: UUID,
) -> OrganizationMember | None:
    """Return the oldest membership for a user, if any."""
    return (
        await OrganizationMember.objects.filter_by(user_id=user_id)
        .order_by(col(OrganizationMember.created_at).asc())
        .first(session)
    )


async def set_active_organization(
    session: AsyncSession,
    *,
    user: User,
    organization_id: UUID,
) -> OrganizationMember:
    """Set a user's active organization and return the membership."""
    member = await get_member(session, user_id=user.id, organization_id=organization_id)
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No org access",
        )
    if user.active_organization_id != organization_id:
        user.active_organization_id = organization_id
        session.add(user)
        await session.commit()
    return member


async def get_active_membership(
    session: AsyncSession,
    user: User,
) -> OrganizationMember | None:
    """Resolve and normalize the user's currently active membership."""
    db_user = await User.objects.by_id(user.id).first(session)
    if db_user is None:
        db_user = user
    if db_user.active_organization_id:
        member = await get_member(
            session,
            user_id=db_user.id,
            organization_id=db_user.active_organization_id,
        )
        if member is not None:
            user.active_organization_id = db_user.active_organization_id
            return member
        db_user.active_organization_id = None
        session.add(db_user)
        await session.commit()
    member = await get_first_membership(session, db_user.id)
    if member is None:
        return None
    await set_active_organization(
        session,
        user=db_user,
        organization_id=member.organization_id,
    )
    user.active_organization_id = db_user.active_organization_id
    return member


async def _find_pending_invite(
    session: AsyncSession,
    email: str,
) -> OrganizationInvite | None:
    return (
        await OrganizationInvite.objects.filter(
            col(OrganizationInvite.accepted_at).is_(None),
            col(OrganizationInvite.invited_email) == email,
        )
        .order_by(col(OrganizationInvite.created_at).asc())
        .first(session)
    )


async def accept_invite(
    session: AsyncSession,
    invite: OrganizationInvite,
    user: User,
) -> OrganizationMember:
    """Accept an invite and create membership plus scoped board access rows."""
    now = utcnow()
    member = OrganizationMember(
        organization_id=invite.organization_id,
        user_id=user.id,
        role=invite.role,
        all_boards_read=invite.all_boards_read,
        all_boards_write=invite.all_boards_write,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    await session.flush()

    # For scoped invites, copy invite board-access rows onto the member at accept
    # time so effective permissions survive invite lifecycle cleanup.
    if not (invite.all_boards_read or invite.all_boards_write):
        access_rows = list(
            await session.exec(
                select(OrganizationInviteBoardAccess).where(
                    col(OrganizationInviteBoardAccess.organization_invite_id) == invite.id,
                ),
            ),
        )
        for row in access_rows:
            session.add(
                OrganizationBoardAccess(
                    organization_member_id=member.id,
                    board_id=row.board_id,
                    can_read=row.can_read,
                    can_write=row.can_write,
                    created_at=now,
                    updated_at=now,
                ),
            )

    invite.accepted_by_user_id = user.id
    invite.accepted_at = now
    invite.updated_at = now
    session.add(invite)
    if user.active_organization_id is None:
        user.active_organization_id = invite.organization_id
        session.add(user)
    await session.commit()
    await session.refresh(member)
    return member


def _get_default_skill_pack_records(org_id: UUID, now: "datetime") -> list[SkillPack]:
    """Build default installer skill pack rows for a new organization."""
    source_base = "https://github.com"
    seen_urls: set[str] = set()
    records: list[SkillPack] = []
    for repo, name, description in DEFAULT_INSTALLER_SKILL_PACKS:
        source_url = _normalize_skill_pack_source_url(f"{source_base}/{repo}")
        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        records.append(
            SkillPack(
                organization_id=org_id,
                name=name,
                description=description,
                source_url=source_url,
                created_at=now,
                updated_at=now,
            ),
        )
    return records


async def _fetch_existing_default_pack_sources(
    session: AsyncSession,
    org_id: UUID,
) -> set[str]:
    """Return existing default skill pack URLs for the organization."""
    if not isinstance(session, AsyncSession):
        return set()
    return {
        _normalize_skill_pack_source_url(row.source_url)
        for row in await SkillPack.objects.filter_by(organization_id=org_id).all(session)
    }


async def ensure_member_for_user(
    session: AsyncSession,
    user: User,
) -> OrganizationMember:
    """Ensure a user has some membership, creating one if necessary."""
    existing = await get_active_membership(session, user)
    if existing is not None:
        return existing

    # Serialize first-time provisioning per user to avoid concurrent duplicate org/member creation.
    await session.exec(
        select(User.id).where(col(User.id) == user.id).with_for_update(),
    )

    existing_member = await get_first_membership(session, user.id)
    if existing_member is not None:
        if user.active_organization_id != existing_member.organization_id:
            user.active_organization_id = existing_member.organization_id
            session.add(user)
            await session.commit()
        return existing_member

    if user.email:
        invite = await _find_pending_invite(session, user.email)
        if invite is not None:
            return await accept_invite(session, invite, user)

    now = utcnow()
    org = Organization(name=DEFAULT_ORG_NAME, created_at=now, updated_at=now)
    session.add(org)
    await session.flush()
    org_id = org.id
    member = OrganizationMember(
        organization_id=org_id,
        user_id=user.id,
        role="owner",
        all_boards_read=True,
        all_boards_write=True,
        created_at=now,
        updated_at=now,
    )
    default_skill_packs = _get_default_skill_pack_records(org_id=org_id, now=now)
    existing_pack_urls = await _fetch_existing_default_pack_sources(session, org_id)
    normalized_existing_pack_urls = {
        _normalize_skill_pack_source_url(existing_pack_source)
        for existing_pack_source in existing_pack_urls
    }
    user.active_organization_id = org_id
    session.add(user)
    session.add(member)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_member = await get_first_membership(session, user.id)
        if existing_member is None:
            raise
        if user.active_organization_id != existing_member.organization_id:
            user.active_organization_id = existing_member.organization_id
            session.add(user)
            await session.commit()
        await session.refresh(existing_member)
        return existing_member

    for pack in default_skill_packs:
        normalized_source_url = _normalize_skill_pack_source_url(pack.source_url)
        if normalized_source_url in normalized_existing_pack_urls:
            continue
        session.add(pack)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            normalized_existing_pack_urls.add(normalized_source_url)
            continue

    await session.refresh(member)
    return member


def member_all_boards_read(member: OrganizationMember) -> bool:
    """Return whether the member has organization-wide read access."""
    return member.all_boards_read or member.all_boards_write


def member_all_boards_write(member: OrganizationMember) -> bool:
    """Return whether the member has organization-wide write access."""
    return member.all_boards_write


async def has_board_access(
    session: AsyncSession,
    *,
    member: OrganizationMember,
    board: Board,
    write: bool,
) -> bool:
    """Return whether a member has board access for the requested mode."""
    if member.organization_id != board.organization_id:
        return False
    if write:
        if member_all_boards_write(member):
            return True
    elif member_all_boards_read(member):
        return True
    access = await OrganizationBoardAccess.objects.filter_by(
        organization_member_id=member.id,
        board_id=board.id,
    ).first(session)
    if access is None:
        return False
    if write:
        return bool(access.can_write)
    return bool(access.can_read or access.can_write)


async def require_board_access(
    session: AsyncSession,
    *,
    user: User,
    board: Board,
    write: bool,
) -> OrganizationMember:
    """Require board access for a user and return matching membership."""
    member = await get_member(
        session,
        user_id=user.id,
        organization_id=board.organization_id,
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No org access",
        )
    if not await has_board_access(session, member=member, board=board, write=write):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Board access denied",
        )
    return member


def board_access_filter(
    member: OrganizationMember,
    *,
    write: bool,
) -> ColumnElement[bool]:
    """Build a SQL filter expression for boards visible to a member."""
    if write and member_all_boards_write(member):
        return col(Board.organization_id) == member.organization_id
    if not write and member_all_boards_read(member):
        return col(Board.organization_id) == member.organization_id
    access_stmt = select(OrganizationBoardAccess.board_id).where(
        col(OrganizationBoardAccess.organization_member_id) == member.id,
    )
    if write:
        access_stmt = access_stmt.where(
            col(OrganizationBoardAccess.can_write).is_(True),
        )
    else:
        access_stmt = access_stmt.where(
            or_(
                col(OrganizationBoardAccess.can_read).is_(True),
                col(OrganizationBoardAccess.can_write).is_(True),
            ),
        )
    return col(Board.id).in_(access_stmt)


async def list_accessible_board_ids(
    session: AsyncSession,
    *,
    member: OrganizationMember,
    write: bool,
) -> list[UUID]:
    """List board ids accessible to a member for read or write mode."""
    if (write and member_all_boards_write(member)) or (
        not write and member_all_boards_read(member)
    ):
        ids = await session.exec(
            select(Board.id).where(
                col(Board.organization_id) == member.organization_id,
            ),
        )
        return list(ids)

    access_stmt = select(OrganizationBoardAccess.board_id).where(
        col(OrganizationBoardAccess.organization_member_id) == member.id,
    )
    if write:
        access_stmt = access_stmt.where(
            col(OrganizationBoardAccess.can_write).is_(True),
        )
    else:
        access_stmt = access_stmt.where(
            or_(
                col(OrganizationBoardAccess.can_read).is_(True),
                col(OrganizationBoardAccess.can_write).is_(True),
            ),
        )
    board_ids = await session.exec(access_stmt)
    return list(board_ids)


async def apply_member_access_update(
    session: AsyncSession,
    *,
    member: OrganizationMember,
    update: OrganizationMemberAccessUpdate,
) -> None:
    """Replace explicit member board-access rows from an access update."""
    now = utcnow()
    member.all_boards_read = update.all_boards_read
    member.all_boards_write = update.all_boards_write
    member.updated_at = now
    session.add(member)

    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.organization_member_id) == member.id,
        commit=False,
    )

    if update.all_boards_read or update.all_boards_write:
        return

    rows = [
        OrganizationBoardAccess(
            organization_member_id=member.id,
            board_id=entry.board_id,
            can_read=entry.can_read,
            can_write=entry.can_write,
            created_at=now,
            updated_at=now,
        )
        for entry in update.board_access
    ]
    session.add_all(rows)


async def apply_invite_board_access(
    session: AsyncSession,
    *,
    invite: OrganizationInvite,
    entries: Iterable[OrganizationBoardAccessSpec],
) -> None:
    """Replace explicit invite board-access rows for an invite."""
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.organization_invite_id) == invite.id,
        commit=False,
    )
    if invite.all_boards_read or invite.all_boards_write:
        return
    now = utcnow()
    rows = [
        OrganizationInviteBoardAccess(
            organization_invite_id=invite.id,
            board_id=entry.board_id,
            can_read=entry.can_read,
            can_write=entry.can_write,
            created_at=now,
            updated_at=now,
        )
        for entry in entries
    ]
    session.add_all(rows)


def normalize_invited_email(email: str) -> str:
    """Normalize an invited email address for storage/comparison."""
    return email.strip().lower()


def normalize_role(role: str) -> str:
    """Normalize a role string and default empty values to `member`."""
    return role.strip().lower() or "member"


def _role_rank(role: str | None) -> int:
    if not role:
        return 0
    return ROLE_RANK.get(role, 0)


async def apply_invite_to_member(
    session: AsyncSession,
    *,
    member: OrganizationMember,
    invite: OrganizationInvite,
) -> None:
    """Apply invite role/access grants onto an existing organization member."""
    now = utcnow()
    member_changed = False
    invite_role = normalize_role(invite.role or "member")
    if _role_rank(invite_role) > _role_rank(member.role):
        member.role = invite_role
        member_changed = True

    if invite.all_boards_read or invite.all_boards_write:
        member.all_boards_read = (
            member.all_boards_read or invite.all_boards_read or invite.all_boards_write
        )
        member.all_boards_write = member.all_boards_write or invite.all_boards_write
        member_changed = True
        if member_changed:
            member.updated_at = now
            session.add(member)
        return

    access_rows = list(
        await session.exec(
            select(OrganizationInviteBoardAccess).where(
                col(OrganizationInviteBoardAccess.organization_invite_id) == invite.id,
            ),
        ),
    )
    for row in access_rows:
        existing = (
            await session.exec(
                select(OrganizationBoardAccess).where(
                    col(OrganizationBoardAccess.organization_member_id) == member.id,
                    col(OrganizationBoardAccess.board_id) == row.board_id,
                ),
            )
        ).first()
        can_write = bool(row.can_write)
        can_read = bool(row.can_read or row.can_write)
        if existing is None:
            session.add(
                OrganizationBoardAccess(
                    organization_member_id=member.id,
                    board_id=row.board_id,
                    can_read=can_read,
                    can_write=can_write,
                    created_at=now,
                    updated_at=now,
                ),
            )
        else:
            existing.can_read = bool(existing.can_read or can_read)
            existing.can_write = bool(existing.can_write or can_write)
            existing.updated_at = now
            session.add(existing)

    if member_changed:
        member.updated_at = now
        session.add(member)
