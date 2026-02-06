from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr


class BoardOnboardingStart(SQLModel):
    pass


class BoardOnboardingAnswer(SQLModel):
    answer: NonEmptyStr
    other_text: str | None = None


class BoardOnboardingConfirm(SQLModel):
    board_type: str
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None

    @model_validator(mode="after")
    def validate_goal_fields(self) -> Self:
        if self.board_type == "goal":
            if not self.objective or not self.success_metrics:
                raise ValueError("Confirmed goal boards require objective and success_metrics")
        return self


class BoardOnboardingQuestionOption(SQLModel):
    id: NonEmptyStr
    label: NonEmptyStr


class BoardOnboardingAgentQuestion(SQLModel):
    question: NonEmptyStr
    options: list[BoardOnboardingQuestionOption] = Field(min_length=1)


def _normalize_optional_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


class BoardOnboardingUserProfile(SQLModel):
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
    def normalize_text(cls, value: Any) -> Any:
        return _normalize_optional_text(value)


LeadAgentAutonomyLevel = Literal["ask_first", "balanced", "autonomous"]
LeadAgentVerbosity = Literal["concise", "balanced", "detailed"]
LeadAgentOutputFormat = Literal["bullets", "mixed", "narrative"]
LeadAgentUpdateCadence = Literal["asap", "hourly", "daily", "weekly"]


class BoardOnboardingLeadAgentDraft(SQLModel):
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
    def normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @field_validator("identity_profile", mode="before")
    @classmethod
    def normalize_identity_profile(cls, value: Any) -> Any:
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
    status: Literal["complete"]
    user_profile: BoardOnboardingUserProfile | None = None
    lead_agent: BoardOnboardingLeadAgentDraft | None = None


BoardOnboardingAgentUpdate = BoardOnboardingAgentComplete | BoardOnboardingAgentQuestion


class BoardOnboardingRead(SQLModel):
    id: UUID
    board_id: UUID
    session_key: str
    status: str
    messages: list[dict[str, object]] | None = None
    draft_goal: BoardOnboardingAgentComplete | None = None
    created_at: datetime
    updated_at: datetime
