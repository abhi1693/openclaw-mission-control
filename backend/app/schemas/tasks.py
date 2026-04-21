"""Schemas for task CRUD and task comment API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr
from app.schemas.tags import TagRef
from app.schemas.task_custom_fields import TaskCustomFieldValues

TaskStatus = Literal["inbox", "in_progress", "review", "rework", "done", "cancelled"]
ReviewPacketType = Literal[
    "frontend_ui",
    "backend_api",
    "review_only",
    "content_copy",
    "infra_ops",
    "mixed",
    "other",
]
ValidationTargetKind = Literal["live_url", "deploy_env", "workspace", "api_base", "other"]
ValidationTargetScope = Literal["review", "runtime", "deploy", "all"]
STATUS_REQUIRED_ERROR = "status is required"
DELIVERY_CONTRACT_REQUIRED_STATUSES = frozenset({"in_progress", "review", "done"})
REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET = frozenset(
    {"frontend_ui", "backend_api", "infra_ops", "mixed"}
)
# Keep these symbols as runtime globals so Pydantic can resolve
# deferred annotations reliably.
RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr, TagRef)


def status_requires_delivery_contract(status: TaskStatus | str | None) -> bool:
    return status in DELIVERY_CONTRACT_REQUIRED_STATUSES


def review_packet_type_requires_validation_target(
    review_packet_type: ReviewPacketType | str | None,
) -> bool:
    return review_packet_type in REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET


def delivery_contract_missing_fields(
    *,
    status: TaskStatus | str | None,
    review_packet_type: ReviewPacketType | str | None,
    validation_target: str | None,
    validation_target_kind: ValidationTargetKind | str | None,
    validation_target_scope: ValidationTargetScope | str | None,
) -> list[str]:
    if not status_requires_delivery_contract(status):
        return []
    missing_fields: list[str] = []
    if review_packet_type is None:
        missing_fields.append("review_packet_type")
        return missing_fields
    if review_packet_type_requires_validation_target(review_packet_type):
        if validation_target is None:
            missing_fields.append("validation_target")
        if validation_target_kind is None:
            missing_fields.append("validation_target_kind")
        if validation_target_scope is None:
            missing_fields.append("validation_target_scope")
    return missing_fields


OWNER_REQUIRED_STATUSES = frozenset({"in_progress", "done"})


def status_requires_assigned_owner(status: TaskStatus | str | None) -> bool:
    """Phase IV §I2: owner required for active states where a specific
    agent is doing (or completed) the work.

    Excludes ``review`` because the codebase's review queue model
    explicitly unassigns on entry — the task awaits a reviewer, the
    assignment happens when they pick it up. Owner IS required for
    ``in_progress`` (someone is working) and ``done`` (someone did
    the work — preserves attribution).
    """

    return status in OWNER_REQUIRED_STATUSES


def actionability_missing_fields(
    *,
    status: TaskStatus | str | None,
    review_packet_type: ReviewPacketType | str | None,
    validation_target: str | None,
    validation_target_kind: ValidationTargetKind | str | None,
    validation_target_scope: ValidationTargetScope | str | None,
    assigned_agent_id: UUID | None,
) -> list[str]:
    """Phase IV §I2: union of delivery-contract fields + the
    assigned-owner check. Tasks entering ``in_progress`` / ``review``
    / ``done`` must carry the contract triplet; ``in_progress`` and
    ``done`` additionally require an owner (see
    ``status_requires_assigned_owner`` for the review-queue nuance).

    Returns the list of missing fields in stable order so callers can
    include it verbatim on the 409 payload without sorting.
    """

    if not status_requires_delivery_contract(status):
        return []
    missing: list[str] = []
    if status_requires_assigned_owner(status) and assigned_agent_id is None:
        missing.append("assigned_agent_id")
    missing.extend(
        delivery_contract_missing_fields(
            status=status,
            review_packet_type=review_packet_type,
            validation_target=validation_target,
            validation_target_kind=validation_target_kind,
            validation_target_scope=validation_target_scope,
        ),
    )
    return missing


class TaskBase(SQLModel):
    """Shared task fields used by task create/read payloads."""

    title: str
    description: str | None = None
    status: TaskStatus = "inbox"
    priority: str = "medium"
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    review_packet_type: ReviewPacketType | None = None
    validation_target: str | None = None
    validation_target_kind: ValidationTargetKind | None = None
    validation_target_scope: ValidationTargetScope | None = None
    operator_decision_required: bool = False
    operator_decision_summary: str | None = None
    depends_on_task_ids: list[UUID] = Field(default_factory=list)
    tag_ids: list[UUID] = Field(default_factory=list)

    @field_validator(
        "validation_target",
        "operator_decision_summary",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_validation_target_triplet(self) -> Self:
        pieces = (
            self.validation_target,
            self.validation_target_kind,
            self.validation_target_scope,
        )
        if any(piece is not None for piece in pieces) and not all(piece is not None for piece in pieces):
            raise ValueError(
                "validation_target, validation_target_kind, and validation_target_scope must be provided together"
            )
        return self


class TaskCreate(TaskBase):
    """Payload for creating a task."""

    created_by_user_id: UUID | None = None
    custom_field_values: TaskCustomFieldValues = Field(default_factory=dict)


class TaskUpdate(SQLModel):
    """Payload for partial task updates."""

    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: str | None = None
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    review_packet_type: ReviewPacketType | None = None
    validation_target: str | None = None
    validation_target_kind: ValidationTargetKind | None = None
    validation_target_scope: ValidationTargetScope | None = None
    operator_decision_required: bool | None = None
    operator_decision_summary: str | None = None
    depends_on_task_ids: list[UUID] | None = None
    tag_ids: list[UUID] | None = None
    custom_field_values: TaskCustomFieldValues | None = None
    comment: NonEmptyStr | None = None

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object | None:
        """Normalize blank comment strings to `None`."""
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "validation_target",
        "operator_decision_summary",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Ensure explicitly supplied status is not null."""
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(STATUS_REQUIRED_ERROR)
        triplet_fields = {
            "validation_target",
            "validation_target_kind",
            "validation_target_scope",
        }
        provided = triplet_fields.intersection(self.model_fields_set)
        if provided and provided != triplet_fields:
            raise ValueError(
                "validation_target, validation_target_kind, and validation_target_scope must be updated together"
            )
        return self


class TaskRead(TaskBase):
    """Task payload returned from read endpoints."""

    id: UUID
    board_id: UUID | None
    created_by_user_id: UUID | None
    in_progress_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    blocked_by_task_ids: list[UUID] = Field(default_factory=list)
    is_blocked: bool = False
    tags: list[TagRef] = Field(default_factory=list)
    custom_field_values: TaskCustomFieldValues | None = None


class TaskCommentCreate(SQLModel):
    """Payload for creating a task comment."""

    message: NonEmptyStr


class TaskCommentRead(SQLModel):
    """Task comment payload returned from read endpoints."""

    id: UUID
    message: str | None
    agent_id: UUID | None
    task_id: UUID | None
    created_at: datetime
    # Phase I: classifier flags stamped at write time. None = not
    # classified; [] = classified, no flags; [str, ...] = flagged.
    classifier_flags: list[str] | None = None
