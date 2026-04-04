"""Pydantic/SQLModel schemas for per-agent model assignment API payloads.

All write endpoints return the same aggregate shape as the primary read so the
UI can re-render from one canonical response without a follow-up GET.

Key invariants:
- manual, recommended/generated, and effective are separate sibling fields.
- State semantics are expressed via explicit status/source/validation fields,
  never inferred from null/empty-array presence alone.
- Empty arrays are transport representation; fallback.status carries the semantic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel

# Enum-like types for request validation
SelectionMode = Literal["manual", "auto"]
OverrideMode = Literal["none", "append", "replace"]
TriggerType = Literal[
    "unavailable", "timeout", "rate_limited",
    "capability_mismatch", "manual_only", "generic",
]


# ---------------------------------------------------------------------------
# Shared leaf types
# ---------------------------------------------------------------------------


class CatalogEntry(SQLModel):
    """A single model in the dynamic catalog."""

    model_id: str = Field(description="Canonical 9router/... model identifier.")
    display_name: str = Field(description="Human-readable display name.")
    provider_family: str = Field(description="Top-level provider, e.g. 9router.")
    routing_family: str = Field(description="Routing sub-family, e.g. ag, cx.")
    family: str = Field(description="Model family, e.g. gemini, claude, gpt.")
    tier: str = Field(
        description="Cost/capability tier: premium | specialized | balanced | budget."
    )
    capability_class: str = Field(
        description="Primary capability: reasoning | general | coding | fast."
    )
    role_fit: list[str] = Field(
        default_factory=list,
        description="Roles this model is suited for: lead, worker, coding, automation, review.",
    )
    supports_primary: bool = Field(default=True, description="Can be used as primary model.")
    supports_fallback: bool = Field(default=True, description="Can be used in fallback chain.")
    status: str = Field(
        default="active",
        description="active | deprecated | unavailable",
    )
    fallback_candidates: list[str] = Field(
        default_factory=list,
        description="Suggested fallback model_ids for this model.",
    )


class ModelCatalogResponse(SQLModel):
    """Response shape for the model catalog endpoint."""

    models: list[CatalogEntry] = Field(description="Available model catalog entries.")
    total: int = Field(description="Total number of entries returned.")
    filters_applied: dict[str, str | bool] = Field(
        default_factory=dict,
        description="Echo of active query filters for client display.",
    )


class FallbackEntry(SQLModel):
    """Single fallback candidate in an ordered list."""

    model_id: str = Field(description="Canonical 9router/... model identifier.")
    position: int = Field(ge=0)
    trigger_type: str = Field(
        default="unavailable",
        description=(
            "When this fallback is considered: "
            "unavailable | timeout | rate_limited | capability_mismatch | manual_only | generic"
        ),
    )
    source: str = Field(description="generated | manual")
    enabled: bool = Field(default=True)
    constraints: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider/capability constraints for this slot.",
    )


class ValidationIssue(SQLModel):
    """Machine-readable validation issue or warning."""

    code: str = Field(description="Stable error/warning code, e.g. no_effective_fallback.")
    severity: str = Field(description="error | warning")
    scope: str = Field(description="primary | fallback | recommendation | global")
    message: str


# ---------------------------------------------------------------------------
# Aggregate sub-sections
# ---------------------------------------------------------------------------


class PrimarySection(SQLModel):
    """Primary model selection state for one agent."""

    manual_model_id: str | None = Field(
        default=None,
        description="Admin-set primary model. Null when selection_mode=auto.",
    )
    recommended_model_id: str | None = Field(
        default=None,
        description="Latest system recommendation. Independent of manual selection.",
    )
    effective_model_id: str | None = Field(
        default=None,
        description=(
            "What runtime should use: manual_model_id when mode=manual, "
            "else recommended_model_id."
        ),
    )
    source: str = Field(
        default="auto",
        description="manual | recommended | none",
    )
    selection_mode: str = Field(
        default="auto",
        description="manual | auto",
    )
    is_valid: bool = Field(
        default=True,
        description="False when effective_model_id references a disabled/invalid model.",
    )
    recommendation_changed: bool = Field(
        default=False,
        description="True when recommended_model_id changed since last admin review.",
    )


class FallbackSection(SQLModel):
    """Fallback policy state for one agent."""

    override_mode: str = Field(
        default="none",
        description="none | append | replace",
    )
    generated_entries: list[FallbackEntry] = Field(default_factory=list)
    manual_entries: list[FallbackEntry] = Field(default_factory=list)
    effective_entries: list[FallbackEntry] = Field(
        default_factory=list,
        description=(
            "Assembled effective fallback list after override_mode precedence "
            "and deduplication are applied."
        ),
    )
    source: str = Field(
        default="generated_only",
        description=(
            "generated_only | manual_only | generated_plus_manual | none"
        ),
    )
    status: str = Field(
        default="empty_invalid",
        description=(
            "configured | empty_allowed | empty_invalid | "
            "invalid_entries | generated_only | manual_only | merged"
        ),
    )
    has_effective_fallback: bool = Field(
        default=False,
        description="True when effective_entries contains at least one valid enabled entry.",
    )
    no_valid_fallback_reason: str | None = Field(
        default=None,
        description=(
            "Human-readable reason when has_effective_fallback=False. "
            "E.g. 'All manual entries duplicate the primary model.'"
        ),
    )


class RecommendationSection(SQLModel):
    """Recommendation metadata for one agent."""

    status: str = Field(
        default="pending",
        description="fresh | stale | error | pending",
    )
    generated_at: datetime | None = Field(default=None)
    version: str | None = Field(default=None)
    explanation: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured explainability payload from recommender.",
    )


class ValidationSection(SQLModel):
    """Validation state for the current assignment config."""

    config_status: str = Field(
        default="pending",
        description="valid | stale | degraded | invalid | pending",
    )
    blocking_issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Issues that prevent safe execution.",
    )
    warnings: list[ValidationIssue] = Field(
        default_factory=list,
        description="Non-blocking issues.",
    )


# ---------------------------------------------------------------------------
# Aggregate read/write shape (single canonical form returned from all surfaces)
# ---------------------------------------------------------------------------


class RuntimeSyncResult(SQLModel):
    """Result of syncing the effective model to the OpenClaw gateway runtime."""

    status: str = Field(
        description="synced | failed | skipped",
        examples=["synced", "failed", "skipped"],
    )
    synced_at: datetime | None = None
    target_path: str | None = None
    error: str | None = None
    next_effective: str = Field(
        default="next_session_start",
        description="When the runtime change takes effect.",
    )


class AgentModelAssignmentRead(SQLModel):
    """Aggregate model assignment payload for one agent.

    Returned by GET, PATCH primary, PUT fallback-override, and POST
    recommendation:regenerate. Clients should never need a follow-up GET.
    """

    agent_id: UUID
    board_id: UUID | None = None
    role_key: str

    primary: PrimarySection
    fallback: FallbackSection
    recommendation: RecommendationSection
    validation: ValidationSection
    runtime_sync: RuntimeSyncResult | None = None

    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Write request schemas
# ---------------------------------------------------------------------------


class PatchPrimaryRequest(SQLModel):
    """Request body for PATCH .../model-assignment/primary."""

    selection_mode: SelectionMode = Field(
        description="manual | auto",
        examples=["manual", "auto"],
    )
    model_id: str | None = Field(
        default=None,
        description="Required when selection_mode=manual. Must be a valid active model_id.",
        examples=["9router/cx/gpt-5.4"],
    )
    reason: str | None = Field(
        default=None,
        description="Optional free-text reason for audit trail.",
    )


class FallbackEntryInput(SQLModel):
    """One fallback entry as supplied in a write request."""

    model_id: str = Field(description="Canonical 9router/... model identifier.")
    position: int = Field(ge=0)
    trigger_type: TriggerType = Field(default="unavailable")
    enabled: bool = Field(default=True)
    constraints: dict[str, Any] | None = None


class PutFallbackOverrideRequest(SQLModel):
    """Request body for PUT .../model-assignment/fallback-override.

    Full-list replacement semantics: the supplied entries list replaces all
    existing manual entries atomically. Ordering is taken from position fields.
    """

    override_mode: OverrideMode = Field(
        description="none | append | replace",
        examples=["replace"],
    )
    entries: list[FallbackEntryInput] = Field(
        default_factory=list,
        description=(
            "Complete set of manual fallback entries. "
            "Replaces any previously stored manual entries."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Optional free-text reason for audit trail.",
    )


class RegenerateRecommendationRequest(SQLModel):
    """Request body for POST .../model-assignment/recommendation:regenerate."""

    reason: str = Field(
        default="admin_requested_refresh",
        description="Why the regeneration was triggered.",
    )
