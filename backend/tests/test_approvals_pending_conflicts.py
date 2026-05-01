from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import approvals as approvals_api
from app.api.deps import ActorContext
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.approvals import ApprovalCreate, ApprovalUpdate


def _test_actor(session: AsyncSession) -> ActorContext:
    """Synthesize a human actor for direct-call test harnesses."""
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    return ActorContext(actor_type="user", user=user)


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
                actor=_test_actor(session),
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
                    actor=_test_actor(session),
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
                actor=_test_actor(session),
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
                    actor=_test_actor(session),
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
            # v2.1: ``create_approval`` only accepts ``pending`` — state
            # transitions go through ``PATCH``. To set up "one resolved +
            # one pending" on the same task, create approval A first
            # (will become the resolved one), PATCH it to approved, then
            # create approval B as the active pending slot.
            resolved_pending = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Review decision completed earlier."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            # Rejected (not approved) so the rehydrate-to-pending path is
            # reachable and we actually exercise the pending-conflict guard.
            # An approved -> pending PATCH is now blocked at the audit-
            # integrity guard before reaching pending-conflict; covered by
            # test_update_approval_forbids_approved_to_pending_overturn_path
            # in test_approvals_idempotency.py.
            resolved = await approvals_api.update_approval(
                approval_id=resolved_pending.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="rejected"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
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
                actor=_test_actor(session),
            )

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=resolved.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="pending"),
                    board=board,
                    session=session,
                    actor=_test_actor(session),
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


@pytest.mark.asyncio
async def test_create_move_to_done_approval_rejects_non_review_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            task = await session.get(Task, task_id)
            assert task is not None
            task.status = "inbox"
            session.add(task)
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await approvals_api.create_approval(
                    payload=ApprovalCreate(
                        action_type="move_to_done",
                        task_id=task_id,
                        payload={"reason": "Close the task."},
                        confidence=95,
                        status="approved",
                    ),
                    board=board,
                    session=session,
                )

            assert exc.value.status_code == 409
            assert exc.value.detail == {
                "message": "move_to_done approvals can only be created for tasks currently in review.",
                "task_ids": [str(task_id)],
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_move_to_done_approval_rejects_review_task_missing_delivery_contract() -> (
    None
):
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            task = await session.get(Task, task_id)
            assert task is not None
            task.status = "review"
            session.add(task)
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await approvals_api.create_approval(
                    payload=ApprovalCreate(
                        action_type="move_to_done",
                        task_id=task_id,
                        payload={"reason": "Close the task."},
                        confidence=95,
                        status="approved",
                    ),
                    board=board,
                    session=session,
                )

            assert exc.value.status_code == 409
            assert exc.value.detail == {
                "message": "move_to_done approvals require a complete delivery contract.",
                "code": "task_delivery_contract_incomplete",
                "task_ids": [str(task_id)],
                "task_details": [
                    {
                        "task_id": str(task_id),
                        "status": "review",
                        # Phase IV §I2: gate validates against target
                        # ``done``, which requires an owner. The test
                        # task has no ``assigned_agent_id`` so it
                        # surfaces alongside the missing packet type.
                        "missing_fields": [
                            "assigned_agent_id",
                            "review_packet_type",
                        ],
                    }
                ],
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_move_to_done_approval_rejects_approval_when_task_left_review() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            task = await session.get(Task, task_id)
            assert task is not None
            task.status = "review"
            # Phase V delivery-contract + Phase IV owner-gate: satisfy
            # both so the setup create_approval call doesn't 409 on a
            # contract check before we can exercise the task-left-review
            # invariant.
            task.review_packet_type = "review_only"
            task.assigned_agent_id = uuid4()
            session.add(task)
            await session.commit()

            actor = _test_actor(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="move_to_done",
                    task_id=task_id,
                    payload={"reason": "Close the task."},
                    confidence=95,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=actor,
            )

            task.status = "inbox"
            session.add(task)
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="approved"),
                    board=board,
                    session=session,
                    actor=actor,
                )

            assert exc.value.status_code == 409
            assert exc.value.detail == {
                "message": "move_to_done approvals can only be created for tasks currently in review.",
                "task_ids": [str(task_id)],
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_move_to_done_approval_rejects_approval_when_review_task_loses_target() -> (
    None
):
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_ids = await _seed_board_with_tasks(session, task_count=1)
            task_id = task_ids[0]
            task = await session.get(Task, task_id)
            assert task is not None
            task.status = "review"
            task.review_packet_type = "frontend_ui"
            task.validation_target = "http://192.168.2.60:3000"
            task.validation_target_kind = "live_url"
            task.validation_target_scope = "review"
            # Phase IV §I2: the move_to_done approval gate validates
            # against the target ``done`` state, which requires an
            # owner. Without one, create_approval would 409 before the
            # test can exercise the update-path validation-drift case.
            task.assigned_agent_id = uuid4()
            session.add(task)
            await session.commit()

            actor = _test_actor(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="move_to_done",
                    task_id=task_id,
                    payload={"reason": "Close the task."},
                    confidence=95,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=actor,
            )

            task.validation_target = None
            task.validation_target_kind = None
            task.validation_target_scope = None
            session.add(task)
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="approved"),
                    board=board,
                    session=session,
                    actor=actor,
                )

            assert exc.value.status_code == 409
            assert exc.value.detail == {
                "message": "move_to_done approvals require a complete delivery contract.",
                "code": "task_delivery_contract_incomplete",
                "task_ids": [str(task_id)],
                "task_details": [
                    {
                        "task_id": str(task_id),
                        "status": "review",
                        "missing_fields": [
                            "validation_target",
                            "validation_target_kind",
                            "validation_target_scope",
                        ],
                    }
                ],
            }
    finally:
        await engine.dispose()
