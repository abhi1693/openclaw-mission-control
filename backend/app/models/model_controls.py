"""SQLModel DB models for per-agent model assignment, fallback, and recommendation history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class AgentModelProfile(QueryModel, table=True):
    """Per-agent model assignment profile.

    Stores admin-controlled assignment intent, latest materialized recommendation
    state, and effective config for fast reads.
    """

    __tablename__ = "agent_model_profiles"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Core identity
    agent_id: UUID = Field(foreign_key="agents.id", index=True, unique=True, nullable=False)
    board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True)
    role_key: str = Field(
        default="worker",
        description="Stable role tag used as recommendation input. E.g. lead, backend, coding.",
    )

    # Primary model selection — admin intent
    primary_model_id: str | None = Field(
        default=None,
        sa_column=Column(Text),
        description="Manually selected primary model_id when selection_mode=manual.",
    )
    primary_selection_mode: str = Field(
        default="auto",
        description="Enum: manual | auto",
    )

    # Recommendation state — system generated, not admin-controlled
    recommended_primary_model_id: str | None = Field(
        default=None,
        sa_column=Column(Text),
        description="Latest recommendation output.",
    )
    recommendation_status: str = Field(
        default="pending",
        description="Enum: fresh | stale | error | pending",
    )
    recommendation_generated_at: datetime | None = Field(default=None)
    recommendation_version: str | None = Field(default=None, sa_column=Column(Text))
    recommendation_explanation: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Structured explanation payload from recommender.",
    )

    # Fallback override — admin intent
    fallback_override_mode: str = Field(
        default="none",
        description="Enum: none | append | replace",
    )
    fallback_override_updated_at: datetime | None = Field(default=None)

    # Materialized effective config — read-optimized denormalized helpers
    effective_primary_model_id: str | None = Field(
        default=None,
        sa_column=Column(Text),
        description=(
            "Denormalized effective primary after override precedence resolution. "
            "Not the source of truth — recomputed after any write."
        ),
    )
    effective_fallback_policy_version: str | None = Field(
        default=None, sa_column=Column(Text)
    )
    effective_config_updated_at: datetime | None = Field(default=None)

    # Validation state
    config_status: str = Field(
        default="pending",
        description="Enum: valid | stale | degraded | invalid | pending",
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentModelFallbackEntry(QueryModel, table=True):
    """Ordered fallback model entry for an agent profile.

    Stores both generated and manual fallback rows in one typed structure.
    Effective fallback list is assembled at read time per override_mode.
    """

    __tablename__ = "agent_model_fallback_entries"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    agent_model_profile_id: UUID = Field(
        foreign_key="agent_model_profiles.id",
        index=True,
        nullable=False,
    )
    source: str = Field(
        description="Enum: generated | manual",
    )
    position: int = Field(
        ge=0,
        description="Zero-based ordering within the source list.",
    )
    model_id: str = Field(sa_column=Column(Text))
    trigger_type: str = Field(
        default="unavailable",
        description="Enum: unavailable | timeout | rate_limited | capability_mismatch | manual_only | generic",
    )
    constraints: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Optional structured constraints for this fallback slot.",
    )
    enabled: bool = Field(default=True)
    generation_version: str | None = Field(
        default=None,
        sa_column=Column(Text),
        description="Set for generated rows to tie back to a recommendation run.",
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentModelRecommendationRun(QueryModel, table=True):
    """Append-only recommendation run history.

    Preserves explainability trail for debugging, staleness detection, and audit.
    """

    __tablename__ = "agent_model_recommendation_runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    board_id: UUID | None = Field(default=None, index=True)
    role_key: str
    catalog_version: str = Field(default="unknown")
    policy_version: str = Field(default="unknown")

    status: str = Field(description="Enum: success | partial | error")
    recommended_primary_model_id: str | None = Field(default=None, sa_column=Column(Text))
    fallback_plan: list[Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Snapshot of generated ordered fallback entries at run time.",
    )
    explanation: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    signals: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Normalized recommendation input signals.",
    )

    generated_at: datetime = Field(default_factory=utcnow)
    error_code: str | None = Field(default=None)
    error_detail: str | None = Field(default=None, sa_column=Column(Text))
