from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import approvals as approvals_api
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.approvals import ApprovalCreate, ApprovalUpdate


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_board_with_tasks(
    session: AsyncSession,
    *,
    task_count: int = 2,
) -> tuple[Board, list[UUID]]:
    org_id = uuid4()
    board = Board(id=uuid4(), organization_id=org_id, name="b", slug="b")
    task_ids = [uuid4() for _ in range(task_count)]

    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(board)
    for task_id in task_ids:
        session.add(Task(id=task_id, board_id=board.id, title=f"task-{task_id}"))
    await session.commit()

    return board, task_ids


@pytest.mark.asyncio
async def test_create_approval_rejects_duplicate_pending_for_same_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.execute",
                    task_id=task_id,
                    payload={"reason": "Initial execution needs confirmation."},
                    confidence=80,
                    status="pending",
                ),
                board=board,
                session=session,
            )
            assert created.task_titles == [f"task-{task_id}"]

            with pytest.raises(HTTPException) as exc:
                await approvals_api.create_approval(
                    payload=ApprovalCreate(
                        action_type="task.retry",
                        task_id=task_id,
                        payload={"reason": "Retry should still be gated."},
                        confidence=77,
                        status="pending",
                    ),
                    board=board,
                    session=session,
                )

            assert exc.value.status_code == 409
            detail = exc.value.detail
            assert isinstance(detail, dict)
            assert detail["message"] == "Each task can have only one pending approval."
            assert len(detail["conflicts"]) == 1
            assert detail["conflicts"][0]["task_id"] == str(task_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_approval_rejects_pending_conflict_from_linked_task_ids() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=2)
            task_a, task_b = task_ids
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.batch_execute",
                    task_ids=[task_a, task_b],
                    payload={"reason": "Batch operation requires sign-off."},
                    confidence=85,
                    status="pending",
                ),
                board=board,
                session=session,
            )
            assert created.task_titles == [f"task-{task_a}", f"task-{task_b}"]

            with pytest.raises(HTTPException) as exc:
                await approvals_api.create_approval(
                    payload=ApprovalCreate(
                        action_type="task.execute",
                        task_id=task_b,
                        payload={"reason": "Single task overlaps with pending batch."},
                        confidence=70,
                        status="pending",
                    ),
                    board=board,
                    session=session,
                )

            assert exc.value.status_code == 409
            detail = exc.value.detail
            assert isinstance(detail, dict)
            assert detail["message"] == "Each task can have only one pending approval."
            assert len(detail["conflicts"]) == 1
            assert detail["conflicts"][0]["task_id"] == str(task_b)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_rejects_reopening_to_pending_with_existing_pending() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            pending = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.execute",
                    task_id=task_id,
                    payload={"reason": "Primary pending approval is active."},
                    confidence=83,
                    status="pending",
                ),
                board=board,
                session=session,
            )
            resolved = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Review decision completed earlier."},
                    confidence=90,
                    status="approved",
                ),
                board=board,
                session=session,
            )

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=resolved.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="pending"),
                    board=board,
                    session=session,
                )

            assert exc.value.status_code == 409
            detail = exc.value.detail
            assert isinstance(detail, dict)
            assert detail["message"] == "Each task can have only one pending approval."
            assert detail["conflicts"] == [
                {
                    "task_id": str(task_id),
                    "approval_id": str(pending.id),
                },
            ]
    finally:
        await engine.dispose()
