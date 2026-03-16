"""Schemas for tag CRUD payloads."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

HEX_COLOR_RE = re.compile(r"^[0-9a-f]{6}$")
RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


def _normalize_color(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower().lstrip("#")
    if not cleaned:
        return None
    if not HEX_COLOR_RE.fullmatch(cleaned):
        raise ValueError("color must be a 6-digit hex value")
    return cleaned


class TagBase(SQLModel):
    """Shared tag fields for create/read payloads."""

    name: str
    slug: str
    color: str = "9e9e9e"
    description: str | None = None


class TagRef(SQLModel):
    """Compact tag representation embedded in task payloads."""

    id: UUID
    name: str
    slug: str
    color: str


class TagCreate(SQLModel):
    """Payload for creating a tag."""

    name: NonEmptyStr
    slug: str | None = None
    color: str = "9e9e9e"
    description: str | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: object) -> object | None:
        """Treat empty slug strings as unset so API can auto-generate."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("color", mode="before")
    @classmethod
    def normalize_color(cls, value: object) -> object:
        """Normalize color to lowercase hex without a leading hash."""
        if isinstance(value, str):
            normalized = _normalize_color(value)
            if normalized is None:
                raise ValueError("color is required")
            return normalized
        return value


class TagUpdate(SQLModel):
    """Payload for partial tag updates."""

    name: NonEmptyStr | None = None
    slug: str | None = None
    color: str | None = None
    description: str | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: object) -> object | None:
        """Treat empty slug strings as unset so API can auto-generate."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("color", mode="before")
    @classmethod
    def normalize_color(cls, value: object) -> object | None:
        """Normalize color to lowercase hex without a leading hash."""
        if value is None:
            return None
        if isinstance(value, str):
            normalized = _normalize_color(value)
            if normalized is None:
                raise ValueError("color must be a 6-digit hex value")
            return normalized
        return value

    @model_validator(mode="after")
    def require_some_update(self) -> Self:
        """Reject empty update payloads to avoid no-op patch calls."""
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class TagRead(TagBase):
    """Tag payload returned from API endpoints."""

    id: UUID
    organization_id: UUID
    task_count: int = 0
    created_at: datetime
    updated_at: datetime
