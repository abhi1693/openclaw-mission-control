"""Schemas for skills marketplace listing and install/uninstall actions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class MarketplaceSkillCreate(SQLModel):
    """Payload used to register a skill URL in the organization marketplace."""

    source_url: AnyHttpUrl
    name: NonEmptyStr | None = None
    description: str | None = None


class SkillPackCreate(SQLModel):
    """Payload used to register a pack URL in the organization."""

    source_url: AnyHttpUrl
    name: NonEmptyStr | None = None
    description: str | None = None
    branch: str = "main"
    metadata_: dict[str, object] = Field(default_factory=dict, alias="metadata")

    model_config = SQLModelConfig(validate_by_name=True)


class MarketplaceSkillRead(SQLModel):
    """Serialized marketplace skill catalog record."""

    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    category: str | None = None
    risk: str | None = None
    source: str | None = None
    source_url: str
    metadata_: dict[str, object] = Field(default_factory=dict, alias="metadata")

    model_config = SQLModelConfig(validate_by_name=True)

    created_at: datetime
    updated_at: datetime


class SkillPackRead(SQLModel):
    """Serialized skill pack record."""

    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    source_url: str
    branch: str
    metadata_: dict[str, object] = Field(default_factory=dict, alias="metadata")

    model_config = SQLModelConfig(validate_by_name=True)

    skill_count: int = 0
    created_at: datetime
    updated_at: datetime


class MarketplaceSkillCardRead(MarketplaceSkillRead):
    """Marketplace card payload with gateway-specific install state."""

    installed: bool
    installed_at: datetime | None = None


class MarketplaceSkillActionResponse(SQLModel):
    """Install/uninstall action response payload."""

    ok: bool = True
    skill_id: UUID
    gateway_id: UUID
    installed: bool


class SkillPackSyncResponse(SQLModel):
    """Pack sync summary payload."""

    ok: bool = True
    pack_id: UUID
    synced: int
    created: int
    updated: int
    warnings: list[str] = Field(default_factory=list)
