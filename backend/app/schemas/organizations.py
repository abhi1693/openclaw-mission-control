"""Schemas for organization, membership, and invite API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class OrganizationRead(SQLModel):
    """Organization payload returned by read endpoints."""

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(SQLModel):
    """Payload for creating a new organization."""

    name: str


class OrganizationActiveUpdate(SQLModel):
    """Payload for switching the active organization context."""

    organization_id: UUID


class OrganizationListItem(SQLModel):
    """Organization list row for current user memberships."""

    id: UUID
    name: str
    role: str
    is_active: bool


class OrganizationUserRead(SQLModel):
    """Embedded user fields included in organization member payloads."""

    id: UUID
    email: str | None = None
    name: str | None = None
    preferred_name: str | None = None


class OrganizationMemberRead(SQLModel):
    """Organization member payload including board-level access overrides."""

    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    all_boards_read: bool
    all_boards_write: bool
    created_at: datetime
    updated_at: datetime
    user: OrganizationUserRead | None = None
    board_access: list[OrganizationBoardAccessRead] = Field(default_factory=list)


class OrganizationMemberUpdate(SQLModel):
    """Payload for partial updates to organization member role."""

    role: str | None = None


class OrganizationBoardAccessSpec(SQLModel):
    """Board access specification used in member/invite mutation payloads."""

    board_id: UUID
    can_read: bool = True
    can_write: bool = False


class OrganizationBoardAccessRead(SQLModel):
    """Board access payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    can_read: bool
    can_write: bool
    created_at: datetime
    updated_at: datetime


class OrganizationMemberAccessUpdate(SQLModel):
    """Payload for replacing organization member access permissions."""

    all_boards_read: bool = False
    all_boards_write: bool = False
    board_access: list[OrganizationBoardAccessSpec] = Field(default_factory=list)


class OrganizationInviteCreate(SQLModel):
    """Payload for creating an organization invite."""

    invited_email: str
    role: str = "member"
    all_boards_read: bool = False
    all_boards_write: bool = False
    board_access: list[OrganizationBoardAccessSpec] = Field(default_factory=list)


class OrganizationInviteRead(SQLModel):
    """Organization invite payload returned from read endpoints."""

    id: UUID
    organization_id: UUID
    invited_email: str
    role: str
    all_boards_read: bool
    all_boards_write: bool
    token: str
    created_by_user_id: UUID | None = None
    accepted_by_user_id: UUID | None = None
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationInviteAccept(SQLModel):
    """Payload for accepting an organization invite token."""

    token: str
