"""Schemas for task custom field metadata, board bindings, and payloads."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, Self
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, date)

TaskCustomFieldType = Literal[
    "text",
    "text_long",
    "integer",
    "decimal",
    "boolean",
    "date",
    "date_time",
    "url",
    "json",
]
TaskCustomFieldUiVisibility = Literal["always", "if_set", "hidden"]
STRING_FIELD_TYPES: set[str] = {"text", "text_long", "date", "date_time", "url"}
TASK_CUSTOM_FIELD_TYPE_ALIASES: dict[str, TaskCustomFieldType] = {
    "text": "text",
    "text_long": "text_long",
    "text (long)": "text_long",
    "long_text": "text_long",
    "integer": "integer",
    "decimal": "decimal",
    "boolean": "boolean",
    "true/false": "boolean",
    "date": "date",
    "date_time": "date_time",
    "date & time": "date_time",
    "datetime": "date_time",
    "url": "url",
    "json": "json",
}
TASK_CUSTOM_FIELD_UI_VISIBILITY_ALIASES: dict[str, TaskCustomFieldUiVisibility] = {
    "always": "always",
    "if_set": "if_set",
    "if set": "if_set",
    "hidden": "hidden",
}

# Reusable alias for task payload payloads containing custom-field values.
TaskCustomFieldValues = dict[str, object | None]


class TaskCustomFieldDefinitionBase(SQLModel):
    """Shared custom field definition properties."""

    field_key: str
    label: str | None = None
    field_type: TaskCustomFieldType = "text"
    ui_visibility: TaskCustomFieldUiVisibility = "always"
    validation_regex: str | None = None
    description: str | None = None
    required: bool = False
    default_value: object | None = None

    @field_validator("field_key", mode="before")
    @classmethod
    def normalize_field_key(cls, value: object) -> object:
        """Normalize field keys to a stable lowercase representation."""
        if not isinstance(value, str):
            raise ValueError("field_key must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("field_key is required")
        return normalized

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        """Normalize labels to a trimmed representation when provided."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("label must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("label is required")
        return normalized

    @field_validator("field_type", mode="before")
    @classmethod
    def normalize_field_type(cls, value: object) -> object:
        """Normalize field type aliases."""
        if not isinstance(value, str):
            raise ValueError("field_type must be a string")
        normalized = value.strip().lower()
        resolved = TASK_CUSTOM_FIELD_TYPE_ALIASES.get(normalized)
        if resolved is None:
            raise ValueError(
                "field_type must be one of: text, text_long, integer, decimal, "
                "boolean, date, date_time, url, json",
            )
        return resolved

    @field_validator("validation_regex", mode="before")
    @classmethod
    def normalize_validation_regex(cls, value: object) -> object:
        """Normalize and validate regex pattern syntax."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("validation_regex must be a string")
        normalized = value.strip()
        if not normalized:
            return None
        try:
            re.compile(normalized)
        except re.error as exc:
            raise ValueError(f"validation_regex is invalid: {exc}") from exc
        return normalized

    @field_validator("ui_visibility", mode="before")
    @classmethod
    def normalize_ui_visibility(cls, value: object) -> object:
        """Normalize UI visibility aliases."""
        if not isinstance(value, str):
            raise ValueError("ui_visibility must be a string")
        normalized = value.strip().lower()
        resolved = TASK_CUSTOM_FIELD_UI_VISIBILITY_ALIASES.get(normalized)
        if resolved is None:
            raise ValueError("ui_visibility must be one of: always, if_set, hidden")
        return resolved


class TaskCustomFieldDefinitionCreate(TaskCustomFieldDefinitionBase):
    """Payload for creating a task custom field definition."""

    field_key: NonEmptyStr
    label: NonEmptyStr | None = None
    board_ids: list[UUID] = Field(min_length=1)

    @field_validator("board_ids")
    @classmethod
    def normalize_board_ids(cls, value: list[UUID]) -> list[UUID]:
        """Remove duplicates while preserving user-supplied order."""
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValueError("board_ids must include at least one board")
        return deduped

    @model_validator(mode="after")
    def default_label_to_field_key(self) -> Self:
        """Default labels to field_key when omitted by older clients."""
        if self.label is None:
            self.label = self.field_key
        return self

    @model_validator(mode="after")
    def validate_regex_field_type_combo(self) -> Self:
        """Restrict regex validation to string-compatible field types."""
        if self.validation_regex is not None and self.field_type not in STRING_FIELD_TYPES:
            raise ValueError(
                "validation_regex is only supported for string field types.",
            )
        return self


class TaskCustomFieldDefinitionUpdate(SQLModel):
    """Payload for editing an existing task custom field definition."""

    label: NonEmptyStr | None = None
    field_type: TaskCustomFieldType | None = None
    ui_visibility: TaskCustomFieldUiVisibility | None = None
    validation_regex: str | None = None
    description: str | None = None
    required: bool | None = None
    default_value: object | None = None
    board_ids: list[UUID] | None = None

    @field_validator("board_ids")
    @classmethod
    def normalize_board_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        """Normalize board bindings when provided in updates."""
        if value is None:
            return None
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValueError("board_ids must include at least one board")
        return deduped

    @field_validator("field_type", mode="before")
    @classmethod
    def normalize_optional_field_type(cls, value: object) -> object:
        """Normalize optional field type aliases."""
        if value is None:
            return None
        return TaskCustomFieldDefinitionBase.normalize_field_type(value)

    @field_validator("validation_regex", mode="before")
    @classmethod
    def normalize_optional_validation_regex(cls, value: object) -> object:
        """Normalize and validate optional regex pattern syntax."""
        if value is None:
            return None
        return TaskCustomFieldDefinitionBase.normalize_validation_regex(value)

    @field_validator("ui_visibility", mode="before")
    @classmethod
    def normalize_optional_ui_visibility(cls, value: object) -> object:
        """Normalize optional UI visibility aliases."""
        if value is None:
            return None
        return TaskCustomFieldDefinitionBase.normalize_ui_visibility(value)

    @model_validator(mode="before")
    @classmethod
    def reject_field_key_update(cls, value: object) -> object:
        """Disallow field_key updates after definition creation."""
        if isinstance(value, dict) and "field_key" in value:
            raise ValueError("field_key cannot be changed after creation.")
        return value

    @model_validator(mode="after")
    def reject_null_for_non_nullable_fields(self) -> Self:
        """Reject explicit null for non-nullable update fields."""
        non_nullable_fields = ("label", "field_type", "ui_visibility", "required")
        invalid = [
            field_name
            for field_name in non_nullable_fields
            if field_name in self.model_fields_set and getattr(self, field_name) is None
        ]
        if invalid:
            raise ValueError(
                f"{', '.join(invalid)} cannot be null; omit the field to leave it unchanged",
            )
        return self

    @model_validator(mode="after")
    def require_some_update(self) -> Self:
        """Reject empty updates to avoid no-op requests."""
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class TaskCustomFieldDefinitionRead(TaskCustomFieldDefinitionBase):
    """Payload returned for custom field definitions."""

    id: UUID
    organization_id: UUID
    label: str
    field_type: TaskCustomFieldType
    ui_visibility: TaskCustomFieldUiVisibility
    validation_regex: str | None = None
    board_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BoardTaskCustomFieldCreate(SQLModel):
    """Payload for binding a definition to a board."""

    task_custom_field_definition_id: UUID


class BoardTaskCustomFieldRead(SQLModel):
    """Payload returned when listing board-bound custom fields."""

    id: UUID
    board_id: UUID
    task_custom_field_definition_id: UUID
    field_key: str
    label: str
    field_type: TaskCustomFieldType
    ui_visibility: TaskCustomFieldUiVisibility
    validation_regex: str | None
    description: str | None
    required: bool
    default_value: object | None
    created_at: datetime


class TaskCustomFieldValuesPayload(SQLModel):
    """Payload for setting all custom-field values at once."""

    custom_field_values: TaskCustomFieldValues = Field(default_factory=dict)


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    return datetime.fromisoformat(normalized)


def validate_custom_field_value(
    *,
    field_type: TaskCustomFieldType,
    value: object | None,
    validation_regex: str | None = None,
) -> None:
    """Validate a custom field value against field type and optional regex."""
    if value is None:
        return

    if field_type in {"text", "text_long"}:
        if not isinstance(value, str):
            raise ValueError("must be a string")
    elif field_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("must be an integer")
    elif field_type == "decimal":
        if (not isinstance(value, (int, float))) or isinstance(value, bool):
            raise ValueError("must be a decimal number")
    elif field_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
    elif field_type == "date":
        if not isinstance(value, str):
            raise ValueError("must be an ISO date string (YYYY-MM-DD)")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an ISO date string (YYYY-MM-DD)") from exc
    elif field_type == "date_time":
        if not isinstance(value, str):
            raise ValueError("must be an ISO datetime string")
        try:
            _parse_iso_datetime(value)
        except ValueError as exc:
            raise ValueError("must be an ISO datetime string") from exc
    elif field_type == "url":
        if not isinstance(value, str):
            raise ValueError("must be a URL string")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be a valid http/https URL")
    elif field_type == "json":
        if not isinstance(value, (dict, list)):
            raise ValueError("must be a JSON object or array")

    if validation_regex is not None and field_type in STRING_FIELD_TYPES:
        if not isinstance(value, str):
            raise ValueError("must be a string for regex validation")
        if re.fullmatch(validation_regex, value) is None:
            raise ValueError("does not match validation_regex")


def validate_custom_field_definition(
    *,
    field_type: TaskCustomFieldType,
    validation_regex: str | None,
    default_value: object | None,
) -> None:
    """Validate field definition constraints and default-value compatibility."""
    if validation_regex is not None and field_type not in STRING_FIELD_TYPES:
        raise ValueError("validation_regex is only supported for string field types.")
    validate_custom_field_value(
        field_type=field_type,
        value=default_value,
        validation_regex=validation_regex,
    )
