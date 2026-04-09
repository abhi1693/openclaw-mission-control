"""Schemas for auto heartbeat governor policy configuration."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActivityTriggerType(str, Enum):
    """Which events count as 'activity' for resetting the backoff ladder."""

    A = "A"  # board chat only
    B = "B"  # board chat OR has_work (assigned in-progress/review)


DurationStr = Annotated[
    str,
    Field(
        description="Duration string like 30s, 5m, 1h, 1d (no disabled).",
        examples=["10m", "1h"],
    ),
]


def _validate_duration(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("duration must be non-empty")
    if value.lower() == "disabled":
        raise ValueError('duration cannot be "disabled"')
    # Simple format: integer + unit.
    # Keep permissive for future; server-side logic still treats these as opaque.
    if not re.match(r"^\d+\s*[smhd]$", value, flags=re.IGNORECASE):
        raise ValueError("duration must match ^\\d+[smhd]$")
    return value.replace(" ", "")


class AutoHeartbeatGovernorPolicyBase(BaseModel):
    enabled: bool = Field(
        default=True,
        description="If false, the governor will not manage heartbeats for this board.",
    )
    ladder: list[DurationStr] = Field(
        default_factory=lambda: ["10m", "30m", "1h", "3h", "6h"],
        description="Backoff ladder values (non-leads).",
    )
    lead_cap_every: DurationStr = Field(
        default="1h",
        description="Max backoff interval for leads.",
    )
    activity_trigger_type: ActivityTriggerType = Field(
        default=ActivityTriggerType.B,
        description="A = board chat only; B = board chat OR assigned work.",
    )

    @field_validator("ladder", mode="before")
    @classmethod
    def _normalize_ladder(cls, value: object) -> object:
        # Accept comma-separated strings from UI forms.
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [p for p in parts if p]
        return value

    @field_validator("ladder")
    @classmethod
    def _validate_ladder(cls, ladder: list[str]) -> list[str]:
        if not ladder:
            raise ValueError("ladder must have at least one value")
        normalized: list[str] = []
        for item in ladder:
            normalized.append(_validate_duration(str(item)))
        return normalized

    @field_validator("lead_cap_every")
    @classmethod
    def _validate_lead_cap(cls, value: str) -> str:
        return _validate_duration(value)


class AutoHeartbeatGovernorPolicyRead(AutoHeartbeatGovernorPolicyBase):
    """Read model for board-scoped governor policy."""


class AutoHeartbeatGovernorPolicyUpdate(BaseModel):
    """Patch model for board-scoped governor policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    ladder: list[DurationStr] | str | None = None
    lead_cap_every: DurationStr | None = None
    activity_trigger_type: ActivityTriggerType | None = None

    @field_validator("ladder", mode="before")
    @classmethod
    def _normalize_ladder(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [p for p in parts if p]
        return value

    @field_validator("ladder")
    @classmethod
    def _validate_ladder(cls, ladder: list[str] | None) -> list[str] | None:
        if ladder is None:
            return None
        if not ladder:
            raise ValueError("ladder must have at least one value")
        return [_validate_duration(str(item)) for item in ladder]

    @field_validator("lead_cap_every")
    @classmethod
    def _validate_lead_cap(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_duration(value)
