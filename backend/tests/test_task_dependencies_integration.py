# ruff: noqa

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.boards import Board
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.services import task_dependencies as td


async def _make_engine() -> AsyncEngine:
    # Single shared in-memory db per engine.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine)


async def _seed_board_and_tasks(
    session: AsyncSession, *, board_id: UUID, task_ids: list[UUID]
) -> None:
    org_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(Board(id=board_id, organization_id=org_id, name="b", slug="b"))
    for tid in task_ids:
        session.add(Task(id=tid, board_id=board_id, title=f"t-{tid}", description=None))
    await session.commit()


@pytest.mark.asyncio
async def test_validate_dependency_update_rejects_self_dependency() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board_id = uuid4()
            task_id = uuid4()
            await _seed_board_and_tasks(session, board_id=board_id, task_ids=[task_id])

            with pytest.raises(HTTPException) as exc:
                await td.validate_dependency_update(
                    session,
                    board_id=board_id,
                    task_id=task_id,
                    depends_on_task_ids=[task_id],
                )
            assert exc.value.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_validate_dependency_update_404s_when_dependency_missing() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board_id = uuid4()
            task_id = uuid4()
            dep_id = uuid4()
            await _seed_board_and_tasks(session, board_id=board_id, task_ids=[task_id])

            with pytest.raises(HTTPException) as exc:
                await td.validate_dependency_update(
                    session,
                    board_id=board_id,
                    task_id=task_id,
                    depends_on_task_ids=[dep_id],
                )
            assert exc.value.status_code == 404
            detail = exc.value.detail
            assert isinstance(detail, dict)
            assert detail["missing_task_ids"] == [str(dep_id)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_validate_dependency_update_detects_cycle() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board_id = uuid4()
            a, b = uuid4(), uuid4()
            await _seed_board_and_tasks(session, board_id=board_id, task_ids=[a, b])

            # existing edge a -> b
            session.add(TaskDependency(board_id=board_id, task_id=a, depends_on_task_id=b))
            await session.commit()

            # update b -> a introduces cycle
            with pytest.raises(HTTPException) as exc:
                await td.validate_dependency_update(
                    session,
                    board_id=board_id,
                    task_id=b,
                    depends_on_task_ids=[a],
                )
            assert exc.value.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dependency_queries_and_replace_and_dependents() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board_id = uuid4()
            t1, t2, t3 = uuid4(), uuid4(), uuid4()
            await _seed_board_and_tasks(session, board_id=board_id, task_ids=[t1, t2, t3])

            # seed deps: t1 depends on t2 then t3
            session.add(TaskDependency(board_id=board_id, task_id=t1, depends_on_task_id=t2))
            session.add(TaskDependency(board_id=board_id, task_id=t1, depends_on_task_id=t3))
            await session.commit()

            # cover empty input short-circuit
            assert await td.dependency_ids_by_task_id(session, board_id=board_id, task_ids=[]) == {}

            deps_map = await td.dependency_ids_by_task_id(
                session, board_id=board_id, task_ids=[t1, t2]
            )
            assert deps_map[t1] == [t2, t3]
            assert deps_map.get(t2, []) == []

            # mark t2 done, t3 not
            task2 = (await session.exec(select(Task).where(col(Task.id) == t2))).first()
            assert task2 is not None
            task2.status = td.DONE_STATUS
            await session.commit()

            # cover empty input short-circuit
            assert (
                await td.dependency_status_by_id(session, board_id=board_id, dependency_ids=[])
                == {}
            )

            status_map = await td.dependency_status_by_id(
                session, board_id=board_id, dependency_ids=[t2, t3]
            )
            assert status_map[t2] == td.DONE_STATUS
            assert status_map[t3] != td.DONE_STATUS

            blocked = await td.blocked_by_for_task(session, board_id=board_id, task_id=t1)
            assert blocked == [t3]

            # cover early return when no deps provided
            assert (
                await td.blocked_by_for_task(
                    session, board_id=board_id, task_id=t1, dependency_ids=[]
                )
                == []
            )

            # replace deps with duplicates (deduped) -> [t3]
            out = await td.replace_task_dependencies(
                session,
                board_id=board_id,
                task_id=t1,
                depends_on_task_ids=[t3, t3],
            )
            await session.commit()
            assert out == [t3]

            deps_map2 = await td.dependency_ids_by_task_id(
                session, board_id=board_id, task_ids=[t1]
            )
            assert deps_map2[t1] == [t3]

            dependents = await td.dependent_task_ids(
                session, board_id=board_id, dependency_task_id=t3
            )
            assert dependents == [t1]

            # also exercise explicit dependency_ids passed
            blocked2 = await td.blocked_by_for_task(
                session, board_id=board_id, task_id=t1, dependency_ids=[t3]
            )
            assert blocked2 == [t3]
    finally:
        await engine.dispose()
