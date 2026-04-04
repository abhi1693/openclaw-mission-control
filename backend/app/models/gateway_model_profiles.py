"""SQLModel for gateway-level model profile defaults (General/Coder/Budget)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel


class GatewayModelProfileDefaults(QueryModel, table=True):
    """Per-gateway model profile defaults.

    Each gateway can define baseline model selections for three profiles:
    - general: required default baseline for all recommendations
    - coder: optional coding-optimized model
    - budget: optional cost-optimized model

    Each field accepts either:
    - A concrete model_id from the active catalog (e.g. "9router/cx/gpt-5.4")
    - The sentinel value "default" (maps to runtime-configured default)
    - None/null (unset — coder/budget fall back to general)

    general_model_id is required when profiles are configured.
    """

    __tablename__ = "gateway_model_profile_defaults"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    gateway_id: UUID = Field(foreign_key="gateways.id", unique=True, index=True)

    general_model_id: str | None = Field(
        default=None,
        description="Required baseline model. 'default' sentinel or catalog model_id.",
    )
    coder_model_id: str | None = Field(
        default=None,
        description="Optional coding-optimized model. Null falls back to general.",
    )
    budget_model_id: str | None = Field(
        default=None,
        description="Optional cost-optimized model. Null falls back to general.",
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
