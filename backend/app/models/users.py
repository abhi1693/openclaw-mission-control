"""User model storing identity and profile preferences."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import Field

from app.models.base import QueryModel


class User(QueryModel, table=True):
    """Application user account and profile attributes."""

    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    clerk_user_id: str = Field(index=True, unique=True)
    email: str | None = Field(default=None, index=True)
    name: str | None = None
    preferred_name: str | None = None
    pronouns: str | None = None
    timezone: str | None = None
    notes: str | None = None
    context: str | None = None
    is_super_admin: bool = Field(default=False)
    active_organization_id: UUID | None = Field(
        default=None,
        foreign_key="organizations.id",
        index=True,
    )
