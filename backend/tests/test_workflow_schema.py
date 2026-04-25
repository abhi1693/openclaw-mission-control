from __future__ import annotations

from uuid import uuid4

from app.schemas.workflows import WorkflowDefinitionCreate, WorkflowRunCreate, WorkflowStepCreate


def test_workflow_definition_requires_trimmed_name_and_slug() -> None:
    created = WorkflowDefinitionCreate(
        name="  Intake workflow  ",
        slug=" intake-workflow ",
        description="  test  ",
    )
    assert created.name == "Intake workflow"
    assert created.slug == "intake-workflow"
    assert created.description == "test"


def test_workflow_run_create_supports_mixed_step_types() -> None:
    run = WorkflowRunCreate(
        title="Launch workflow",
        workflow_definition_id=uuid4(),
        steps=[
            WorkflowStepCreate(step_key="triage", title="Triage", step_type="agent_task"),
            WorkflowStepCreate(step_key="approve", title="Approve", step_type="approval"),
            WorkflowStepCreate(step_key="human", title="Human step", step_type="human_task"),
        ],
    )
    assert len(run.steps) == 3
    assert run.steps[1].step_type == "approval"
    assert run.steps[2].step_type == "human_task"
