from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import ActorContext
from app.api.workflows import create_workflow_run, get_workflow_run, update_workflow_step
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.workflows import WorkflowRunCreate, WorkflowStepCreate, WorkflowStepUpdate


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _seed(session: AsyncSession) -> tuple[Board, Agent, Task]:
    organization_id = uuid4()
    gateway = Gateway(
        id=uuid4(),
        organization_id=organization_id,
        name="gateway",
        url="https://gateway.local",
        workspace_root="/tmp/workspace",
    )
    board = Board(
        id=uuid4(),
        organization_id=organization_id,
        gateway_id=gateway.id,
        name="board",
        slug=f"board-{uuid4()}",
        description="board",
    )
    agent = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="agent",
        status="online",
    )
    task = Task(id=uuid4(), board_id=board.id, title="task")
    session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
    session.add(gateway)
    session.add(board)
    session.add(agent)
    session.add(task)
    await session.commit()
    return board, agent, task


@pytest.mark.asyncio
async def test_create_and_update_workflow_run_roundtrip() -> None:
    engine = await _make_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            board, agent, task = await _seed(session)
            actor = ActorContext(actor_type="agent", agent=agent)

            created = await create_workflow_run(
                payload=WorkflowRunCreate(
                    title="workflow",
                    source_task_id=task.id,
                    status="running",
                    current_step_key="triage",
                    steps=[
                        WorkflowStepCreate(
                            step_key="triage",
                            title="Triage",
                            step_type="agent_task",
                            status="running",
                            task_id=task.id,
                        ),
                        WorkflowStepCreate(
                            step_key="review",
                            title="Review",
                            step_type="human_task",
                            status="waiting_human",
                        ),
                    ],
                ),
                board=board,
                session=session,
                actor=actor,
            )

            assert created.title == "workflow"
            assert len(created.steps) == 2
            assert created.steps[1].status == "waiting_human"

            updated_step = await update_workflow_step(
                step_id=created.steps[1].id,
                payload=WorkflowStepUpdate(status="completed"),
                board=board,
                session=session,
                actor=actor,
            )
            assert updated_step.status == "completed"
            assert updated_step.completed_at is not None

            fetched = await get_workflow_run(
                run_id=created.id,
                board=board,
                session=session,
                _actor=actor,
            )
            assert fetched.id == created.id
            assert len(fetched.steps) == 2
            assert fetched.steps[1].status == "completed"
    finally:
        await engine.dispose()
