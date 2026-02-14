from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import col, select, SQLModel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api.deps import ActorContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.tasks import TaskUpdate


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_non_lead_agent_can_update_status_for_assigned_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=worker_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assigned task",
                    description="",
                    status="inbox",
                    assigned_agent_id=worker_id,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="in_progress"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == worker_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_forbidden_without_assigned_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            actor_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=actor_id,
                    name="actor",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="unassigned task",
                    description="",
                    status="inbox",
                    assigned_agent_id=None,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == actor_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="in_progress"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 403
            assert isinstance(exc.value.detail, dict)
            assert exc.value.detail["code"] == "task_assignee_required"
            assert exc.value.detail["message"] == "Agents can only change status on tasks assigned to them."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_forbidden_when_task_assigned_to_other_agent() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            actor_id = uuid4()
            assignee_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=actor_id,
                    name="actor",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Agent(
                    id=assignee_id,
                    name="other",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="other owner task",
                    description="",
                    status="inbox",
                    assigned_agent_id=assignee_id,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == actor_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="in_progress"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 403
            assert isinstance(exc.value.detail, dict)
            assert exc.value.detail["code"] == "task_assignee_mismatch"
            assert exc.value.detail["message"] == "Agents can only change status on tasks assigned to them."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_forbidden_for_lead_only_patch_fields() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            actor_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=actor_id,
                    name="actor",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="owned task",
                    description="",
                    status="inbox",
                    assigned_agent_id=actor_id,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == actor_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(assigned_agent_id=actor_id),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 403
            assert isinstance(exc.value.detail, dict)
            assert exc.value.detail["code"] == "task_update_field_forbidden"
    finally:
        await engine.dispose()
