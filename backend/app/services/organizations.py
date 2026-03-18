"""Organization membership and board-access service helpers.

Simplified for single-user local deployment. The organization/member model is
retained as a namespace but all access checks always pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.db import crud
from app.models.boards import Board
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.skills import SkillPack
from app.models.users import User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.sql.elements import ColumnElement

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


@dataclass(frozen=True)
class OrganizationContext:
    """Resolved organization and membership for the active user."""

    organization: Organization
    member: OrganizationMember


def is_org_admin(member: OrganizationMember) -> bool:
    """Single-user mode: always admin."""
    return True


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
    db_user.active_organization_id = member.organization_id
    session.add(db_user)
    await session.commit()
    user.active_organization_id = db_user.active_organization_id
    return member


def _get_default_skill_pack_records(org_id: UUID, now: "object") -> list[SkillPack]:
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

    existing_member = await get_first_membership(session, user.id)
    if existing_member is not None:
        if user.active_organization_id != existing_member.organization_id:
            user.active_organization_id = existing_member.organization_id
            session.add(user)
            await session.commit()
        return existing_member

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


async def require_board_access(
    session: AsyncSession,
    *,
    user: User,
    board: Board,
    write: bool,
) -> OrganizationMember:
    """Single-user mode: always grant access. Return the user's membership."""
    member = await get_member(
        session,
        user_id=user.id,
        organization_id=board.organization_id,
    )
    if member is None:
        member = await ensure_member_for_user(session, user)
    return member


def board_access_filter(
    member: OrganizationMember,
    *,
    write: bool,
) -> ColumnElement[bool]:
    """Single-user mode: return all boards in the organization."""
    return col(Board.organization_id) == member.organization_id


async def list_accessible_board_ids(
    session: AsyncSession,
    *,
    member: OrganizationMember,
    write: bool,
) -> list[UUID]:
    """Single-user mode: all boards are accessible."""
    ids = await session.exec(
        select(Board.id).where(
            col(Board.organization_id) == member.organization_id,
        ),
    )
    return list(ids)
