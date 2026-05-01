"""Tests for approval-resolution idempotency and terminal-conflict guards.

Mirrors the OpenClaw 2026.4.27 gateway-side contract: duplicate same-decision
PATCHes against an already-resolved approval are idempotent, and conflicting
terminal flips return an explicit ``already-resolved`` error rather than
silently overwriting state.
"""

from __future__ import annotations

from typing import Any, cast
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


async def _seed_board_with_task(session: AsyncSession) -> tuple[Board, UUID]:
    org_id = uuid4()
    board = Board(id=uuid4(), organization_id=org_id, name="b", slug="b")
    task_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(board)
    session.add(Task(id=task_id, board_id=board.id, title=f"task-{task_id}"))
    await session.commit()
    return board, task_id


@pytest.mark.asyncio
async def test_update_approval_is_idempotent_for_same_decision_approve() -> None:
    """PATCH ``status=approved`` on an already-approved approval is a no-op.

    The second PATCH must not bump ``resolved_at``, write a history event,
    or fire a lead notification. The returned payload must reflect the
    already-resolved state from the first PATCH.
    """
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "First decision."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            first = await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="approved"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            assert first.status == "approved"
            assert first.resolved_at is not None
            initial_resolved_at = first.resolved_at

            second = await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="approved"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            assert second.status == "approved"
            assert second.resolved_at == initial_resolved_at, (
                "idempotent re-resolve must not mutate resolved_at"
            )
            assert second.id == first.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_is_idempotent_for_same_decision_reject() -> None:
    """Same idempotency contract for the rejected→rejected path."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Reject path."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            first = await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="rejected"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            assert first.status == "rejected"
            initial_resolved_at = first.resolved_at

            second = await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="rejected"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            assert second.status == "rejected"
            assert second.resolved_at == initial_resolved_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_rejects_conflicting_terminal_flip_approve_to_reject() -> None:
    """An approve→reject flip on an already-resolved approval must 409."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Approve first."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="approved"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="rejected"),
                    board=board,
                    session=session,
                    actor=_test_actor(session),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            detail = cast(dict[str, Any], exc.value.detail)
            assert detail["current_status"] == "approved"
            assert detail["requested_status"] == "rejected"
            assert detail["approval_id"] == str(created.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_forbids_approved_to_pending_overturn_path() -> None:
    """Codex F2 (re-pass): the 2-PATCH overturn approved → pending → rejected
    must be blocked at the first PATCH. Without this guard, the conflict
    guard above is trivially bypassable.
    """
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "First decision."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="approved"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="pending"),
                    board=board,
                    session=session,
                    actor=_test_actor(session),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            detail = cast(dict[str, Any], exc.value.detail)
            assert detail["current_status"] == "approved"
            assert detail["requested_status"] == "pending"
            assert "overturn" in detail["message"].lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_allows_rejected_to_pending_resubmission() -> None:
    """Codex F2: the legitimate rehydrate path (rejected → pending re-submit
    after worker addresses the rejection) must remain working. Only
    ``approved → pending`` is forbidden, not ``rejected → pending``.
    """
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "First decision."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="rejected"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            # rejected → pending must succeed (worker re-submitting)
            rehydrated = await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="pending"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            assert rehydrated.status == "pending"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_uses_for_update_lock_on_approval_row() -> None:
    """Codex F1: the approval read must hold a row lock until commit.

    Verified by intercepting the SQL statement compilation and asserting
    the ``FOR UPDATE`` clause is present. SQLite does not honor the lock
    at runtime, so we cannot test the race itself in this harness — but
    the clause must be in the compiled query so PostgreSQL on .66 enforces
    it.
    """
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Lock test."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            # Spy on session.exec to capture the FIRST SELECT statement
            # produced during update_approval (the locking read).
            from unittest import mock

            captured: list[Any] = []
            original_exec = session.exec

            async def spy_exec(statement, *args, **kwargs):
                captured.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
                return await original_exec(statement, *args, **kwargs)

            with mock.patch.object(session, "exec", spy_exec):
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="approved"),
                    board=board,
                    session=session,
                    actor=_test_actor(session),
                )

            # The first compiled SELECT against the approvals table must
            # include FOR UPDATE.
            approval_selects = [
                sql for sql in captured if "FROM approvals" in sql or "approvals" in sql.lower()
            ]
            assert approval_selects, "no SELECT against approvals table observed"
            first_select = approval_selects[0]
            assert "FOR UPDATE" in first_select.upper(), (
                f"locking SELECT missing FOR UPDATE clause: {first_select}"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_approval_rejects_conflicting_terminal_flip_reject_to_approve() -> None:
    """A reject→approve flip on an already-resolved approval must 409."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task_id = await _seed_board_with_task(session)
            created = await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.review",
                    task_id=task_id,
                    payload={"reason": "Reject first."},
                    confidence=90,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=_test_actor(session),
            )
            await approvals_api.update_approval(
                approval_id=created.id,  # type: ignore[arg-type]
                payload=ApprovalUpdate(status="rejected"),
                board=board,
                session=session,
                actor=_test_actor(session),
            )

            with pytest.raises(HTTPException) as exc:
                await approvals_api.update_approval(
                    approval_id=created.id,  # type: ignore[arg-type]
                    payload=ApprovalUpdate(status="approved"),
                    board=board,
                    session=session,
                    actor=_test_actor(session),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            detail = cast(dict[str, Any], exc.value.detail)
            assert detail["current_status"] == "rejected"
            assert detail["requested_status"] == "approved"
    finally:
        await engine.dispose()
