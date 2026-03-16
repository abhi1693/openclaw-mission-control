"""Task custom field models and board binding helpers."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, Column, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class TaskCustomFieldDefinition(TenantScoped, table=True):
    """Reusable custom field definition for task metadata."""

    __tablename__ = "task_custom_field_definitions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "field_key",
            name="uq_task_custom_field_definitions_org_id_field_key",
        ),
        CheckConstraint(
            "field_type IN ('text','text_long','integer','decimal','boolean','date','date_time','url','json')",
            name="ck_tcf_def_field_type",
        ),
        CheckConstraint(
            "ui_visibility IN ('always','if_set','hidden')",
            name="ck_tcf_def_ui_visibility",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    field_key: str = Field(index=True)
    label: str
    field_type: str = Field(default="text")
    ui_visibility: str = Field(default="always")
    validation_regex: str | None = None
    description: str | None = None
    required: bool = Field(default=False)
    default_value: object | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BoardTaskCustomField(TenantScoped, table=True):
    """Board-level binding of a custom field definition."""

    __tablename__ = "board_task_custom_fields"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "board_id",
            "task_custom_field_definition_id",
            name="uq_board_task_custom_fields_board_id_task_custom_field_definition_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_custom_field_definition_id: UUID = Field(
        foreign_key="task_custom_field_definitions.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)


class TaskCustomFieldValue(TenantScoped, table=True):
    """Stored task-level values for bound custom fields."""

    __tablename__ = "task_custom_field_values"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "task_custom_field_definition_id",
            name="uq_task_custom_field_values_task_id_task_custom_field_definition_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    task_custom_field_definition_id: UUID = Field(
        foreign_key="task_custom_field_definitions.id",
        index=True,
    )
    value: object | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
