"""Organization invite model for email-based tenant membership flow."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class OrganizationInvite(QueryModel, table=True):
    """Invitation record granting prospective organization access."""

    __tablename__ = "organization_invites"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("token", name="uq_org_invites_token"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    invited_email: str = Field(index=True)
    token: str = Field(index=True)
    role: str = Field(default="member", index=True)
    all_boards_read: bool = Field(default=False)
    all_boards_write: bool = Field(default=False)
    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    accepted_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    accepted_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
