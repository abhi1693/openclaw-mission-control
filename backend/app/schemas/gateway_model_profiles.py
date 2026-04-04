"""Schemas for gateway model profile defaults API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel


# ---------------------------------------------------------------------------
# Response sub-types
# ---------------------------------------------------------------------------


class ProfileSlotRead(SQLModel):
    """Read shape for a single profile slot (general/coder/budget)."""

    model_id: str | None = Field(
        default=None,
        description=(
            "Concrete catalog model_id, 'default' sentinel, or null (unset)."
        ),
    )
    source: str = Field(
        default="unset",
        description=(
            "How this slot's value was determined: "
            "explicit | default_sentinel | fallback_to_general | unset"
        ),
    )
    display_name: str | None = Field(
        default=None,
        description="Resolved display name from catalog. Null when unset or 'default'.",
    )
    effective_model_id: str | None = Field(
        default=None,
        description=(
            "Resolved model_id after fallback logic. "
            "For coder/budget: falls back to general when null."
        ),
    )


# ---------------------------------------------------------------------------
# Aggregate read shape
# ---------------------------------------------------------------------------


class GatewayModelProfileDefaultsRead(SQLModel):
    """Full gateway model profile defaults response."""

    gateway_id: UUID
    general: ProfileSlotRead
    coder: ProfileSlotRead
    budget: ProfileSlotRead
    updated_at: datetime | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Write request
# ---------------------------------------------------------------------------


class PatchGatewayModelProfileDefaultsRequest(SQLModel):
    """PATCH request for gateway model profile defaults.

    All fields are optional — only provided fields are updated.
    Set a field to null to clear it (revert to unset/fallback).
    Set a field to "default" to use the runtime default sentinel.
    """

    general_model_id: str | None = Field(
        default=None,
        description=(
            "'default' sentinel or concrete catalog model_id. "
            "Required baseline — cannot be cleared once set."
        ),
    )
    coder_model_id: str | None = Field(
        default=None,
        description=(
            "'default' sentinel, concrete catalog model_id, or null to clear."
        ),
    )
    budget_model_id: str | None = Field(
        default=None,
        description=(
            "'default' sentinel, concrete catalog model_id, or null to clear."
        ),
    )
