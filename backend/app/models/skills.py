"""Skill-related SQLModel tables for marketplace, packs, and installations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class MarketplaceSkill(TenantScoped, table=True):
    """A marketplace skill entry that can be installed onto one or more gateways."""

    __tablename__ = "marketplace_skills"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_url",
            name="uq_marketplace_skills_org_source_url",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    name: str
    description: str | None = Field(default=None)
    category: str | None = Field(default=None)
    risk: str | None = Field(default=None)
    source: str | None = Field(default=None)
    source_url: str
    metadata_: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SkillPack(TenantScoped, table=True):
    """A pack repository URL that can be synced into marketplace skills."""

    __tablename__ = "skill_packs"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_url",
            name="uq_skill_packs_org_source_url",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    name: str
    description: str | None = Field(default=None)
    source_url: str
    branch: str = Field(default="main")
    metadata_: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GatewayInstalledSkill(QueryModel, table=True):
    """Marks that a marketplace skill is installed for a specific gateway."""

    __tablename__ = "gateway_installed_skills"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "gateway_id",
            "skill_id",
            name="uq_gateway_installed_skills_gateway_id_skill_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    gateway_id: UUID = Field(foreign_key="gateways.id", index=True)
    skill_id: UUID = Field(foreign_key="marketplace_skills.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
