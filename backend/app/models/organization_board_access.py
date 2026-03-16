"""Board-level access grants assigned to organization members."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class OrganizationBoardAccess(QueryModel, table=True):
    """Member-specific board permissions within an organization."""

    __tablename__ = "organization_board_access"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_member_id",
            "board_id",
            name="uq_org_board_access_member_board",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_member_id: UUID = Field(
        foreign_key="organization_members.id",
        index=True,
    )
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    can_read: bool = Field(default=True)
    can_write: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
