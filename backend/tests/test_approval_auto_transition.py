# ruff: noqa: INP001
"""Auto-transition task to ``done`` when an operator approves a
``move_to_done`` approval.

Today the operator's PATCH on the approval flips the row to
``status=approved`` and notifies the lead via gateway dispatch — the
lead then runs ``lead-review-routing`` on its next heartbeat tick and
PATCHes the task to ``done``. That round-trip is 5-15 minutes of
wake-discovery latency for what is otherwise a deterministic
transition: the approval API has already validated the same gates the
lead would re-check (``_ensure_move_to_done_targets_in_review``,
``_ensure_move_to_done_targets_have_delivery_contract``).

The fix: the approval API itself drives the status transition to
``done`` immediately after committing the approval. The lead still
gets the notification for audit and downstream routing, but doesn't
need to be the gating step.

These tests are RED until the auto-transition is wired into
``update_approval``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import approvals as approvals_api
from app.api.deps import ActorContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.approvals import ApprovalCreate, ApprovalUpdate


def _user_actor(session: AsyncSession) -> ActorContext:
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    return ActorContext(actor_type="user", user=user)


async def _seed_board_and_review_task(
    session: AsyncSession,
    *,
    review_packet_type: str = "review_only",
    task_status: str = "review",
) -> tuple[Board, Agent, Task]:
    """Seed an org/gateway/board with a worker agent + a task that
    satisfies the move_to_done delivery-contract gate (assigned_agent
    + review_packet_type=review_only which doesn't require a
    validation_target)."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    worker_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{board_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{board_id}",
            url="ws://example/ws",
            workspace_root="/tmp/wks",
        ),
    )
    board = Board(id=board_id, organization_id=org_id, name="b", slug=f"b-{board_id.hex[:6]}")
    session.add(board)
    worker = Agent(
        id=worker_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name=f"worker-{worker_id.hex[:6]}",
        auth_token=f"tok-{uuid4().hex}",
    )
    session.add(worker)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{task_id.hex[:6]}",
        status=task_status,
        review_packet_type=review_packet_type,
        assigned_agent_id=worker_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, worker, task


@pytest.mark.asyncio
async def test_approving_move_to_done_auto_transitions_task_to_done(
    sqlite_session: AsyncSession,
) -> None:
    """The operator's approval PATCH (status=approved) must drive the
    target task to status=done in the same response cycle, no longer
    waiting for the lead's next heartbeat tick."""
    session = sqlite_session
    board, worker, task = await _seed_board_and_review_task(session)
    actor = _user_actor(session)

    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="move_to_done",
            task_id=task.id,
            payload={"reason": "ready for done"},
            confidence=92,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )

    refreshed = (await session.exec(select(Task).where(Task.id == task.id))).first()
    assert refreshed is not None
    assert refreshed.status == "done", (
        f"expected task auto-transitioned to done after approval; "
        f"got status={refreshed.status!r}"
    )


@pytest.mark.asyncio
async def test_approving_non_move_to_done_action_leaves_task_status_unchanged(
    sqlite_session: AsyncSession,
) -> None:
    """Auto-transition fires only for action_types in
    DONE_APPROVAL_ACTION_TYPES. An approval for some other action
    (e.g. ``task.execute``) must NOT move the task even when approved."""
    session = sqlite_session
    board, worker, task = await _seed_board_and_review_task(session)
    actor = _user_actor(session)

    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task.id,
            payload={"reason": "execute"},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )

    refreshed = (await session.exec(select(Task).where(Task.id == task.id))).first()
    assert refreshed is not None
    assert refreshed.status == "review", (
        f"expected non-done action_type to leave task status unchanged; "
        f"got status={refreshed.status!r}"
    )


@pytest.mark.asyncio
async def test_idempotent_when_approval_already_resolved(
    sqlite_session: AsyncSession,
) -> None:
    """A PATCH to the same terminal status (approved -> approved) on an
    already-resolved approval is the existing idempotent no-op path. The
    auto-transition must not re-fire and must not move an already-done
    task back to anything else."""
    session = sqlite_session
    board, worker, task = await _seed_board_and_review_task(session)
    actor = _user_actor(session)

    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="move_to_done",
            task_id=task.id,
            payload={"reason": "ready"},
            confidence=92,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )
    # Second PATCH same-status. Existing API path is idempotent (returns
    # current state). The auto-transition must not re-fire.
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )
    refreshed = (await session.exec(select(Task).where(Task.id == task.id))).first()
    assert refreshed is not None
    assert refreshed.status == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action_type",
    [
        "move_to_done",
        "mark_done",
        "task_done",
        "task_done_transition",
        "move_task_to_done",
        "mark_task_done",
    ],
)
async def test_all_done_aliases_trigger_auto_transition(
    sqlite_session: AsyncSession,
    action_type: str,
) -> None:
    """All canonical action_type aliases in DONE_APPROVAL_ACTION_TYPES
    must trigger the auto-transition. Production gap 2026-05-07: an
    E.07 approval used `task_done_transition` (a Supervisor-emitted
    alias not yet in the canonical set), so the approval flipped to
    approved but the task stayed in `review`."""
    session = sqlite_session
    board, worker, task = await _seed_board_and_review_task(session)
    actor = _user_actor(session)
    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type=action_type,
            task_id=task.id,
            payload={"reason": "alias-test"},
            confidence=92,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )
    refreshed = (await session.exec(select(Task).where(Task.id == task.id))).first()
    assert refreshed is not None
    assert refreshed.status == "done", (
        f"alias {action_type!r} should trigger auto-transition; " f"got status={refreshed.status!r}"
    )


@pytest.mark.asyncio
async def test_rejecting_does_not_auto_transition(
    sqlite_session: AsyncSession,
) -> None:
    """Rejecting a move_to_done approval must NOT move the task."""
    session = sqlite_session
    board, worker, task = await _seed_board_and_review_task(session)
    actor = _user_actor(session)

    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="move_to_done",
            task_id=task.id,
            payload={"reason": "needs more"},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=pending.id,
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=actor,
    )
    refreshed = (await session.exec(select(Task).where(Task.id == task.id))).first()
    assert refreshed is not None
    assert refreshed.status == "review"
