"""Schemas used by the board-onboarding assistant flow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

_RUNTIME_TYPE_REFERENCES = (datetime, UUID, NonEmptyStr)


class BoardOnboardingStart(SQLModel):
    """Start signal for initializing onboarding conversation."""


class BoardOnboardingAnswer(SQLModel):
    """User answer payload for a single onboarding question."""

    answer: NonEmptyStr
    other_text: str | None = None


class BoardOnboardingConfirm(SQLModel):
    """Payload used to confirm generated onboarding draft fields."""

    board_type: str
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None

    @model_validator(mode="after")
    def validate_goal_fields(self) -> Self:
        """Require goal metadata when the board type is `goal`."""
        if self.board_type == "goal" and (not self.objective or not self.success_metrics):
            message = "Confirmed goal boards require objective and success_metrics"
            raise ValueError(message)
        return self


class BoardOnboardingQuestionOption(SQLModel):
    """Selectable option for an onboarding question."""

    id: NonEmptyStr
    label: NonEmptyStr


class BoardOnboardingAgentQuestion(SQLModel):
    """Question payload emitted by the onboarding assistant."""

    question: NonEmptyStr
    options: list[BoardOnboardingQuestionOption] = Field(min_length=1)


def _normalize_optional_text(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


class BoardOnboardingUserProfile(SQLModel):
    """User-profile preferences gathered during onboarding."""

    preferred_name: str | None = None
    pronouns: str | None = None
    timezone: str | None = None
    notes: str | None = None
    context: str | None = None

    @field_validator(
        "preferred_name",
        "pronouns",
        "timezone",
        "notes",
        "context",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object | None:
        """Trim optional free-form profile text fields."""
        return _normalize_optional_text(value)


LeadAgentAutonomyLevel = Literal["ask_first", "balanced", "autonomous"]
LeadAgentVerbosity = Literal["concise", "balanced", "detailed"]
LeadAgentOutputFormat = Literal["bullets", "mixed", "narrative"]
LeadAgentUpdateCadence = Literal["asap", "hourly", "daily", "weekly"]


class BoardOnboardingLeadAgentDraft(SQLModel):
    """Editable lead-agent draft configuration."""

    name: NonEmptyStr | None = None
    # role, communication_style, emoji are expected keys.
    identity_profile: dict[str, str] | None = None
    autonomy_level: LeadAgentAutonomyLevel | None = None
    verbosity: LeadAgentVerbosity | None = None
    output_format: LeadAgentOutputFormat | None = None
    update_cadence: LeadAgentUpdateCadence | None = None
    custom_instructions: str | None = None

    @field_validator(
        "autonomy_level",
        "verbosity",
        "output_format",
        "update_cadence",
        "custom_instructions",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, value: object) -> object | None:
        """Trim optional lead-agent preference fields."""
        return _normalize_optional_text(value)

    @field_validator("identity_profile", mode="before")
    @classmethod
    def normalize_identity_profile(
        cls,
        value: object,
    ) -> object | None:
        """Normalize identity profile keys and values as trimmed strings."""
        if value is None:
            return None
        if not isinstance(value, dict):
            return value
        normalized: dict[str, str] = {}
        for raw_key, raw_val in value.items():
            if raw_val is None:
                continue
            key = str(raw_key).strip()
            if not key:
                continue
            val = str(raw_val).strip()
            if val:
                normalized[key] = val
        return normalized or None


class BoardOnboardingAgentComplete(BoardOnboardingConfirm):
    """Complete onboarding draft produced by the onboarding assistant."""

    status: Literal["complete"]
    user_profile: BoardOnboardingUserProfile | None = None
    lead_agent: BoardOnboardingLeadAgentDraft | None = None


BoardOnboardingAgentUpdate = BoardOnboardingAgentComplete | BoardOnboardingAgentQuestion


class BoardOnboardingRead(SQLModel):
    """Stored onboarding session state returned by API endpoints."""

    id: UUID
    board_id: UUID
    session_key: str
    status: str
    messages: list[dict[str, object]] | None = None
    draft_goal: BoardOnboardingAgentComplete | None = None
    created_at: datetime
    updated_at: datetime
