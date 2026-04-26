"""Workflow definition/run/step models for first-class workflow tracking."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class WorkflowDefinition(TenantScoped, table=True):
    """Repeatable workflow template scoped to an organization and optional board."""

    __tablename__ = "workflow_definitions"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True)
    name: str
    slug: str = Field(index=True)
    description: str | None = None
    version: int = Field(default=1)
    status: str = Field(default="draft", index=True)
    trigger_mode: str = Field(default="manual", index=True)
    step_graph_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    default_policy_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowRun(TenantScoped, table=True):
    """Execution instance for a workflow definition."""

    __tablename__ = "workflow_runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    workflow_definition_id: UUID | None = Field(
        default=None,
        foreign_key="workflow_definitions.id",
        index=True,
    )
    source_task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    title: str
    status: str = Field(default="pending", index=True)
    current_step_key: str | None = Field(default=None, index=True)
    created_by_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    created_by_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    context_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    result_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowStep(TenantScoped, table=True):
    """Materialized step belonging to a workflow run."""

    __tablename__ = "workflow_steps"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    step_key: str = Field(index=True)
    title: str
    step_type: str = Field(default="agent_task", index=True)
    status: str = Field(default="pending", index=True)
    assigned_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    assigned_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    approval_id: UUID | None = Field(default=None, foreign_key="approvals.id", index=True)
    depends_on_step_ids_json: list[str] | None = Field(default=None, sa_column=Column(JSON))
    instructions: str | None = None
    input_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    output_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    due_at: datetime | None = None
    sort_order: int = Field(default=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowStepEvent(TenantScoped, table=True):
    """Structured audit event for workflow runs and steps."""

    __tablename__ = "workflow_step_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    workflow_step_id: UUID | None = Field(default=None, foreign_key="workflow_steps.id", index=True)
    actor_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    actor_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    event_type: str = Field(index=True)
    payload_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
