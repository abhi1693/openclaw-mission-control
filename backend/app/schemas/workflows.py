"""Schemas for workflow definitions, runs, and steps."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import Field, SQLModel

WorkflowDefinitionStatus = Literal["draft", "active", "archived"]
WorkflowTriggerMode = Literal["manual", "task_status", "webhook", "schedule", "api"]
WorkflowRunStatus = Literal[
    "pending",
    "running",
    "blocked",
    "waiting_human",
    "waiting_approval",
    "completed",
    "failed",
    "canceled",
]
WorkflowStepType = Literal[
    "agent_task",
    "human_task",
    "approval",
    "notification",
    "wait",
    "decision",
    "subworkflow",
]
WorkflowStepStatus = Literal[
    "pending",
    "ready",
    "running",
    "blocked",
    "waiting_human",
    "waiting_approval",
    "completed",
    "failed",
    "skipped",
    "canceled",
]
RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class WorkflowDefinitionBase(SQLModel):
    name: str
    slug: str
    description: str | None = None
    version: int = 1
    status: WorkflowDefinitionStatus = "draft"
    trigger_mode: WorkflowTriggerMode = "manual"
    step_graph_json: dict[str, object] | None = None
    default_policy_json: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_strings(self) -> Self:
        self.name = self.name.strip()
        self.slug = self.slug.strip()
        if not self.name:
            raise ValueError("name is required")
        if not self.slug:
            raise ValueError("slug is required")
        if self.description is not None:
            self.description = self.description.strip() or None
        return self


class WorkflowDefinitionCreate(WorkflowDefinitionBase):
    board_id: UUID | None = None


class WorkflowDefinitionUpdate(SQLModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    version: int | None = None
    status: WorkflowDefinitionStatus | None = None
    trigger_mode: WorkflowTriggerMode | None = None
    step_graph_json: dict[str, object] | None = None
    default_policy_json: dict[str, object] | None = None


class WorkflowDefinitionRead(WorkflowDefinitionBase):
    id: UUID
    organization_id: UUID
    board_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowStepCreate(SQLModel):
    step_key: str
    title: str
    step_type: WorkflowStepType = "agent_task"
    status: WorkflowStepStatus = "pending"
    assigned_user_id: UUID | None = None
    assigned_agent_id: UUID | None = None
    task_id: UUID | None = None
    approval_id: UUID | None = None
    depends_on_step_ids: list[UUID] = Field(default_factory=list)
    instructions: str | None = None
    input_json: dict[str, object] | None = None
    output_json: dict[str, object] | None = None
    due_at: datetime | None = None
    sort_order: int = 0


class WorkflowStepUpdate(SQLModel):
    status: WorkflowStepStatus | None = None
    assigned_user_id: UUID | None = None
    assigned_agent_id: UUID | None = None
    task_id: UUID | None = None
    approval_id: UUID | None = None
    instructions: str | None = None
    input_json: dict[str, object] | None = None
    output_json: dict[str, object] | None = None
    due_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowStepRead(SQLModel):
    id: UUID
    workflow_run_id: UUID
    step_key: str
    title: str
    step_type: WorkflowStepType
    status: WorkflowStepStatus
    assigned_user_id: UUID | None = None
    assigned_agent_id: UUID | None = None
    task_id: UUID | None = None
    approval_id: UUID | None = None
    depends_on_step_ids: list[UUID] = Field(default_factory=list)
    instructions: str | None = None
    input_json: dict[str, object] | None = None
    output_json: dict[str, object] | None = None
    due_at: datetime | None = None
    sort_order: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowRunCreate(SQLModel):
    workflow_definition_id: UUID | None = None
    source_task_id: UUID | None = None
    title: str
    status: WorkflowRunStatus = "pending"
    current_step_key: str | None = None
    context_json: dict[str, object] | None = None
    result_json: dict[str, object] | None = None
    steps: list[WorkflowStepCreate] = Field(default_factory=list)


class WorkflowRunUpdate(SQLModel):
    status: WorkflowRunStatus | None = None
    current_step_key: str | None = None
    context_json: dict[str, object] | None = None
    result_json: dict[str, object] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowRunRead(SQLModel):
    id: UUID
    board_id: UUID
    workflow_definition_id: UUID | None = None
    source_task_id: UUID | None = None
    title: str
    status: WorkflowRunStatus
    current_step_key: str | None = None
    created_by_user_id: UUID | None = None
    created_by_agent_id: UUID | None = None
    context_json: dict[str, object] | None = None
    result_json: dict[str, object] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepRead] = Field(default_factory=list)


class WorkflowRunSummary(SQLModel):
    id: UUID
    title: str
    status: WorkflowRunStatus
    current_step_key: str | None = None
    source_task_id: UUID | None = None
    waiting_step_count: int = 0
    approval_step_count: int = 0
    human_step_count: int = 0
    created_at: datetime
    updated_at: datetime
