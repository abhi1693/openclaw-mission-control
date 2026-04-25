"""Workflow definition/run/step endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.activity_events import ActivityEvent
from app.models.boards import Board
from app.models.workflows import WorkflowDefinition, WorkflowRun, WorkflowStep, WorkflowStepEvent
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.workflows import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionRead,
    WorkflowDefinitionUpdate,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunSummary,
    WorkflowRunUpdate,
    WorkflowStepRead,
    WorkflowStepUpdate,
)
from app.services.activity_log import record_activity

if False:  # pragma: no cover
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/boards/{board_id}", tags=["workflows"])

SESSION_DEP = Depends(get_session)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
ACTOR_DEP = Depends(require_user_or_agent)


def _step_dep_ids(step: WorkflowStep) -> list[UUID]:
    raw = step.depends_on_step_ids_json or []
    output: list[UUID] = []
    for item in raw:
        try:
            output.append(UUID(str(item)))
        except ValueError:
            continue
    return output


def _step_read(step: WorkflowStep) -> WorkflowStepRead:
    return WorkflowStepRead(
        id=step.id,
        workflow_run_id=step.workflow_run_id,
        step_key=step.step_key,
        title=step.title,
        step_type=step.step_type,
        status=step.status,
        assigned_user_id=step.assigned_user_id,
        assigned_agent_id=step.assigned_agent_id,
        task_id=step.task_id,
        approval_id=step.approval_id,
        depends_on_step_ids=_step_dep_ids(step),
        instructions=step.instructions,
        input_json=step.input_json,
        output_json=step.output_json,
        due_at=step.due_at,
        sort_order=step.sort_order,
        started_at=step.started_at,
        completed_at=step.completed_at,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


async def _run_steps(session: AsyncSession, *, run_id: UUID) -> list[WorkflowStep]:
    return (
        await WorkflowStep.objects.filter_by(workflow_run_id=run_id)
        .order_by(col(WorkflowStep.sort_order).asc(), col(WorkflowStep.created_at).asc())
        .all(session)
    )


async def _run_read(session: AsyncSession, run: WorkflowRun) -> WorkflowRunRead:
    return WorkflowRunRead(
        id=run.id,
        board_id=run.board_id,
        workflow_definition_id=run.workflow_definition_id,
        source_task_id=run.source_task_id,
        title=run.title,
        status=run.status,
        current_step_key=run.current_step_key,
        created_by_user_id=run.created_by_user_id,
        created_by_agent_id=run.created_by_agent_id,
        context_json=run.context_json,
        result_json=run.result_json,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[_step_read(step) for step in await _run_steps(session, run_id=run.id)],
    )


def _run_summary(run: WorkflowRun, *, steps: list[WorkflowStep]) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        id=run.id,
        title=run.title,
        status=run.status,
        current_step_key=run.current_step_key,
        source_task_id=run.source_task_id,
        waiting_step_count=sum(1 for step in steps if step.status in {"waiting_human", "waiting_approval"}),
        approval_step_count=sum(1 for step in steps if step.step_type == "approval"),
        human_step_count=sum(1 for step in steps if step.step_type == "human_task"),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


async def _record_workflow_event(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    actor: ActorContext,
    event_type: str,
    message: str,
    step: WorkflowStep | None = None,
    payload_json: dict[str, object] | None = None,
) -> None:
    workflow_event = WorkflowStepEvent(
        workflow_run_id=run.id,
        workflow_step_id=step.id if step else None,
        actor_user_id=actor.user.id if actor.actor_type == "user" and actor.user else None,
        actor_agent_id=actor.agent.id if actor.actor_type == "agent" and actor.agent else None,
        event_type=event_type,
        payload_json=payload_json,
    )
    session.add(workflow_event)
    record_activity(
        session,
        event_type=event_type,
        message=message,
        agent_id=workflow_event.actor_agent_id,
        task_id=run.source_task_id,
        board_id=run.board_id,
    )


@router.get("/workflows", response_model=DefaultLimitOffsetPage[WorkflowDefinitionRead])
async def list_workflow_definitions(
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
):
    statement = (
        WorkflowDefinition.objects.filter(
            (col(WorkflowDefinition.organization_id) == board.organization_id)
            & ((col(WorkflowDefinition.board_id) == board.id) | (col(WorkflowDefinition.board_id).is_(None)))
        )
        .order_by(col(WorkflowDefinition.created_at).desc())
        .statement
    )
    return await paginate(session, statement)


@router.post("/workflows", response_model=WorkflowDefinitionRead)
async def create_workflow_definition(
    payload: WorkflowDefinitionCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> WorkflowDefinition:
    workflow = WorkflowDefinition.model_validate(
        {
            **payload.model_dump(),
            "organization_id": board.organization_id,
            "board_id": payload.board_id if payload.board_id is not None else board.id,
        }
    )
    return await crud.create(session, WorkflowDefinition, **workflow.model_dump())


@router.patch("/workflows/{workflow_id}", response_model=WorkflowDefinitionRead)
async def update_workflow_definition(
    workflow_id: UUID,
    payload: WorkflowDefinitionUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> WorkflowDefinition:
    workflow = await WorkflowDefinition.objects.by_id(workflow_id).first(session)
    if workflow is None or workflow.organization_id != board.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    crud.apply_updates(workflow, updates)
    workflow.updated_at = utcnow()
    return await crud.save(session, workflow)


@router.get("/workflow-runs", response_model=DefaultLimitOffsetPage[WorkflowRunSummary])
async def list_workflow_runs(
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
):
    statement = (
        WorkflowRun.objects.filter_by(board_id=board.id)
        .order_by(col(WorkflowRun.created_at).desc())
        .statement
    )

    async def _transform(items: list[object]) -> list[WorkflowRunSummary]:
        runs = [item for item in items if isinstance(item, WorkflowRun)]
        summaries: list[WorkflowRunSummary] = []
        for run in runs:
            summaries.append(_run_summary(run, steps=await _run_steps(session, run_id=run.id)))
        return summaries

    return await paginate(session, statement, transformer=_transform)


@router.post("/workflow-runs", response_model=WorkflowRunRead)
async def create_workflow_run(
    payload: WorkflowRunCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> WorkflowRunRead:
    workflow_definition = None
    if payload.workflow_definition_id is not None:
        workflow_definition = await WorkflowDefinition.objects.by_id(payload.workflow_definition_id).first(session)
        if workflow_definition is None or workflow_definition.organization_id != board.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow definition not found")
    run = WorkflowRun(
        board_id=board.id,
        workflow_definition_id=payload.workflow_definition_id,
        source_task_id=payload.source_task_id,
        title=payload.title.strip(),
        status=payload.status,
        current_step_key=payload.current_step_key,
        context_json=payload.context_json,
        result_json=payload.result_json,
        created_by_user_id=actor.user.id if actor.actor_type == "user" and actor.user else None,
        created_by_agent_id=actor.agent.id if actor.actor_type == "agent" and actor.agent else None,
        started_at=utcnow() if payload.status == "running" else None,
    )
    session.add(run)
    await session.flush()
    created_steps: list[WorkflowStep] = []
    for index, step_payload in enumerate(payload.steps):
        step = WorkflowStep(
            workflow_run_id=run.id,
            step_key=step_payload.step_key,
            title=step_payload.title,
            step_type=step_payload.step_type,
            status=step_payload.status,
            assigned_user_id=step_payload.assigned_user_id,
            assigned_agent_id=step_payload.assigned_agent_id,
            task_id=step_payload.task_id,
            approval_id=step_payload.approval_id,
            depends_on_step_ids_json=[str(value) for value in step_payload.depends_on_step_ids],
            instructions=step_payload.instructions,
            input_json=step_payload.input_json,
            output_json=step_payload.output_json,
            due_at=step_payload.due_at,
            sort_order=step_payload.sort_order if step_payload.sort_order else index,
            started_at=utcnow() if step_payload.status == "running" else None,
            completed_at=utcnow() if step_payload.status == "completed" else None,
        )
        session.add(step)
        created_steps.append(step)
    await _record_workflow_event(
        session,
        run=run,
        actor=actor,
        event_type="workflow.run.created",
        message=f"Workflow run created: {run.title}.",
        payload_json={
            "workflow_definition_id": str(workflow_definition.id) if workflow_definition else None,
            "step_count": len(created_steps),
        },
    )
    await session.commit()
    await session.refresh(run)
    return await _run_read(session, run)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(
    run_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> WorkflowRunRead:
    run = await WorkflowRun.objects.by_id(run_id).first(session)
    if run is None or run.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await _run_read(session, run)


@router.patch("/workflow-runs/{run_id}", response_model=WorkflowRunRead)
async def update_workflow_run(
    run_id: UUID,
    payload: WorkflowRunUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> WorkflowRunRead:
    run = await WorkflowRun.objects.by_id(run_id).first(session)
    if run is None or run.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    previous_status = run.status
    crud.apply_updates(run, updates)
    if "status" in updates and updates["status"] == "completed" and run.completed_at is None:
        run.completed_at = utcnow()
    if "status" in updates and updates["status"] == "running" and run.started_at is None:
        run.started_at = utcnow()
    run.updated_at = utcnow()
    session.add(run)
    await _record_workflow_event(
        session,
        run=run,
        actor=actor,
        event_type="workflow.run.updated",
        message=f"Workflow run updated: {run.title} ({previous_status} -> {run.status}).",
        payload_json={"previous_status": previous_status, "status": run.status},
    )
    await session.commit()
    await session.refresh(run)
    return await _run_read(session, run)


@router.patch("/workflow-steps/{step_id}", response_model=WorkflowStepRead)
async def update_workflow_step(
    step_id: UUID,
    payload: WorkflowStepUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> WorkflowStepRead:
    step = await WorkflowStep.objects.by_id(step_id).first(session)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    run = await WorkflowRun.objects.by_id(step.workflow_run_id).first(session)
    if run is None or run.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    previous_status = step.status
    updates = payload.model_dump(exclude_unset=True)
    crud.apply_updates(step, updates)
    if "status" in updates and updates["status"] == "running" and step.started_at is None:
        step.started_at = utcnow()
    if "status" in updates and updates["status"] == "completed" and step.completed_at is None:
        step.completed_at = utcnow()
    step.updated_at = utcnow()
    session.add(step)
    await _record_workflow_event(
        session,
        run=run,
        step=step,
        actor=actor,
        event_type="workflow.step.updated",
        message=f"Workflow step updated: {step.title} ({previous_status} -> {step.status}).",
        payload_json={"previous_status": previous_status, "status": step.status, "step_key": step.step_key},
    )
    await session.commit()
    await session.refresh(step)
    return _step_read(step)


@router.delete("/workflow-runs/{run_id}", response_model=OkResponse)
async def delete_workflow_run(
    run_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> OkResponse:
    run = await WorkflowRun.objects.by_id(run_id).first(session)
    if run is None or run.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await crud.delete_where(session, WorkflowStepEvent, col(WorkflowStepEvent.workflow_run_id) == run.id)
    await crud.delete_where(session, WorkflowStep, col(WorkflowStep.workflow_run_id) == run.id)
    await crud.delete(session, run)
    return OkResponse()
