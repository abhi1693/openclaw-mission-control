from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.activity_events import ActivityEvent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.workflows import WorkflowDefinition, WorkflowRun, WorkflowStep
from app.services.board_snapshot import build_board_snapshot


@pytest.mark.asyncio
async def test_board_snapshot_includes_workflow_run_summaries() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                )
            )
            board = Board(
                id=board_id,
                organization_id=org_id,
                gateway_id=gateway_id,
                name="Board",
                slug="board",
                description="Workflow board",
            )
            task = Task(id=uuid4(), board_id=board_id, title="Task")
            session.add(board)
            session.add(task)
            definition = WorkflowDefinition(
                organization_id=org_id,
                board_id=board_id,
                name="Plan workflow",
                slug="plan-workflow",
                status="active",
            )
            session.add(definition)
            await session.flush()
            run = WorkflowRun(
                board_id=board_id,
                workflow_definition_id=definition.id,
                source_task_id=task.id,
                title="Plan workflow run",
                status="waiting_human",
                current_step_key="review",
            )
            session.add(run)
            await session.flush()
            session.add(
                WorkflowStep(
                    workflow_run_id=run.id,
                    step_key="review",
                    title="Human review",
                    step_type="human_task",
                    status="waiting_human",
                    task_id=task.id,
                    sort_order=0,
                )
            )
            session.add(
                Approval(
                    board_id=board_id,
                    task_id=task.id,
                    action_type="task.review",
                    confidence=90,
                    status="pending",
                )
            )
            session.add(ActivityEvent(event_type="task.created", task_id=task.id, board_id=board_id))
            await session.commit()

            snapshot = await build_board_snapshot(session, board)

            assert len(snapshot.workflow_runs) == 1
            summary = snapshot.workflow_runs[0]
            assert summary.title == "Plan workflow run"
            assert summary.status == "waiting_human"
            assert summary.current_step_key == "review"
            assert summary.human_step_count == 1
            assert summary.waiting_step_count == 1
    finally:
        await engine.dispose()
