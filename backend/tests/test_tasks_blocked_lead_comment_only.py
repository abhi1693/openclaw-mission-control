# ruff: noqa: INP001

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import ActorContext
from app.api.tasks import _TaskUpdateInput, _apply_lead_task_update
from app.models.agents import Agent
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_lead_dependency_only_update_allowed_when_task_blocked() -> None:
    """Leads may update dependencies even if the task is currently blocked.

    This supports unblocking work by adjusting dependency graphs, while still
    rejecting status/assignee transitions.
    """

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            lead_id = uuid4()
            dep_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(Board(id=board_id, organization_id=org_id, name="b", slug="b"))
            session.add(
                Agent(
                    id=lead_id,
                    name="Lead",
                    board_id=board_id,
                    gateway_id=uuid4(),
                    is_board_lead=True,
                    openclaw_session_id="agent:lead:session",
                ),
            )
            session.add(Task(id=dep_id, board_id=board_id, title="dep", description=None))
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="t",
                    description=None,
                    status="review",
                    assigned_agent_id=None,
                ),
            )
            session.add(
                TaskDependency(
                    board_id=board_id,
                    task_id=task_id,
                    depends_on_task_id=dep_id,
                ),
            )
            await session.commit()

            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert lead is not None
            assert task is not None

            # Re-assert the same deps list; this should be a no-op and should not
            # be rejected solely because the task is blocked.
            update = _TaskUpdateInput(
                task=task,
                actor=ActorContext(actor_type="agent", agent=lead),
                board_id=board_id,
                previous_status=task.status,
                previous_assigned=task.assigned_agent_id,
                status_requested=False,
                updates={},
                comment=None,
                depends_on_task_ids=[dep_id],
                tag_ids=None,
                custom_field_values={},
                custom_field_values_set=False,
            )

            result = await _apply_lead_task_update(session, update=update)
            assert result.id == task_id

            reloaded = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert reloaded is not None
            assert reloaded.status == "review"
            assert reloaded.assigned_agent_id is None

    finally:
        await engine.dispose()
