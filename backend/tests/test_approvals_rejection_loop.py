"""Tests for the rejection-loop guard + unblock endpoint.

Covers the v2 design that replaced the spoofable v1 ``@miguel`` string
match. Properties exercised:

- Three consecutive rejections on the same task return 409.
- An ``approved`` event in the middle of a rejection streak resets the
  counter.
- The authenticated ``unblock`` endpoint (human user) clears the loop
  and the next submission is allowed.
- Ordinary worker agents cannot unblock; only board leads and humans.
- The loop guard is per-task, not board-global: rejections on task A
  do not block task B.
- String-matching spoof attempts (payload or comment) no longer work.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import approvals as approvals_api
from app.api.deps import ActorContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.approvals import ApprovalCreate, ApprovalUnblock, ApprovalUpdate


async def _seed(
    session: AsyncSession,
    *,
    task_count: int = 1,
) -> tuple[Board, list[UUID], Gateway]:
    org_id = uuid4()
    board = Board(id=uuid4(), organization_id=org_id, name="b", slug="b")
    gateway = Gateway(
        id=uuid4(),
        organization_id=org_id,
        url="ws://example/ws",
        name="test-gateway",
        workspace_root="/tmp/test-workspace",
    )
    task_ids = [uuid4() for _ in range(task_count)]
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(gateway)
    session.add(board)
    for task_id in task_ids:
        session.add(Task(id=task_id, board_id=board.id, title=f"task-{task_id}"))
    await session.commit()
    return board, task_ids, gateway


def _user_actor(session: AsyncSession) -> ActorContext:
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    return ActorContext(actor_type="user", user=user)


async def _lead_agent(session: AsyncSession, gateway_id: UUID, board_id: UUID) -> Agent:
    agent = Agent(
        id=uuid4(),
        gateway_id=gateway_id,
        board_id=board_id,
        name=f"lead-{uuid4().hex[:8]}",
        is_board_lead=True,
        auth_token=f"tok-{uuid4().hex}",
    )
    session.add(agent)
    await session.flush()
    return agent


async def _worker_agent(session: AsyncSession, gateway_id: UUID, board_id: UUID) -> Agent:
    agent = Agent(
        id=uuid4(),
        gateway_id=gateway_id,
        board_id=board_id,
        name=f"worker-{uuid4().hex[:8]}",
        is_board_lead=False,
        auth_token=f"tok-{uuid4().hex}",
    )
    session.add(agent)
    await session.flush()
    return agent


async def _reject_cycle(
    session: AsyncSession,
    *,
    board: Board,
    task_id: UUID,
    actor: ActorContext,
) -> UUID:
    """Submit an approval as pending and immediately reject it.

    Returns the approval id so the test can reopen/unblock it.
    """
    created = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "Cycle submission."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=created.id,
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=actor,
    )
    return created.id  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_third_consecutive_rejection_blocks_new_submission(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, _ = await _seed(session)
    task_id = task_ids[0]
    actor = _user_actor(session)

    # 1st cycle: submit + reject
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    # 2nd cycle: submit + reject
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    # 3rd cycle: submit + reject
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)

    # 4th submission must 409
    with pytest.raises(HTTPException) as exc:
        await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.execute",
                task_id=task_id,
                payload={"reason": "Fourth attempt."},
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert "Rejection loop detected" in str(detail)


@pytest.mark.asyncio
async def test_approved_event_resets_the_streak(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, _ = await _seed(session)
    task_id = task_ids[0]
    actor = _user_actor(session)

    # 2 rejections
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)

    # Approved event in the middle clears the streak. Create
    # pending then PATCH to approved (the only supported path
    # now — create_approval forces pending).
    pending = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "Actually good this time."},
            confidence=95,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    approved = await approvals_api.update_approval(
        approval_id=pending.id,  # type: ignore[arg-type]
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,
        actor=actor,
    )
    assert approved.status == "approved"

    # 2 more rejections — still under 3 consecutive after the reset
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)

    # 3rd new submission should be allowed (streak was reset by approved)
    fresh = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "After reset."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    assert fresh.status == "pending"


@pytest.mark.asyncio
async def test_unblock_endpoint_clears_the_loop_for_human_user(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, _ = await _seed(session)
    task_id = task_ids[0]
    actor = _user_actor(session)

    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    await _reject_cycle(session, board=board, task_id=task_id, actor=actor)
    last_approval_id = await _reject_cycle(session, board=board, task_id=task_id, actor=actor)

    # Without unblock, a new submission is blocked
    with pytest.raises(HTTPException) as exc:
        await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.execute",
                task_id=task_id,
                payload={"reason": "Blocked attempt."},
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
    assert exc.value.status_code == 409

    # Unblock as human user
    await approvals_api.unblock_approval(
        approval_id=last_approval_id,
        payload=ApprovalUnblock(
            reason="Operator reviewed: new commit verified behavioral fix.",
        ),
        board=board,
        session=session,
        actor=_user_actor(session),
    )

    # Next submission passes
    fresh = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "After unblock."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    assert fresh.status == "pending"


@pytest.mark.asyncio
async def test_worker_agent_cannot_unblock(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, gateway = await _seed(session)
    task_id = task_ids[0]
    user_actor = _user_actor(session)

    # Create an initial approval so the unblock has a target row
    created = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "Initial submission."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=user_actor,
    )

    worker = await _worker_agent(session, gateway.id, board.id)
    worker_actor = ActorContext(actor_type="agent", agent=worker)

    with pytest.raises(HTTPException) as exc:
        await approvals_api.unblock_approval(
            approval_id=created.id,
            payload=ApprovalUnblock(reason="Self-unblock attempt."),
            board=board,
            session=session,
            actor=worker_actor,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_board_lead_agent_can_unblock(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, gateway = await _seed(session)
    task_id = task_ids[0]
    user_actor = _user_actor(session)

    # Rack up 3 rejections
    await _reject_cycle(session, board=board, task_id=task_id, actor=user_actor)
    await _reject_cycle(session, board=board, task_id=task_id, actor=user_actor)
    last = await _reject_cycle(session, board=board, task_id=task_id, actor=user_actor)

    lead = await _lead_agent(session, gateway.id, board.id)
    lead_actor = ActorContext(actor_type="agent", agent=lead)

    # Lead agent unblocks successfully
    await approvals_api.unblock_approval(
        approval_id=last,
        payload=ApprovalUnblock(reason="Lead reviewed the new commit."),
        board=board,
        session=session,
        actor=lead_actor,
    )

    # Next submission passes
    fresh = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "Post-lead-unblock."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=user_actor,
    )
    assert fresh.status == "pending"


@pytest.mark.asyncio
async def test_loop_guard_is_per_task_not_board_global(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, task_ids, _ = await _seed(session, task_count=2)
    task_a, task_b = task_ids
    actor = _user_actor(session)

    # 3 rejections on task A
    await _reject_cycle(session, board=board, task_id=task_a, actor=actor)
    await _reject_cycle(session, board=board, task_id=task_a, actor=actor)
    await _reject_cycle(session, board=board, task_id=task_a, actor=actor)

    # Task B should still be freely submittable
    fresh = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_b,
            payload={"reason": "Unrelated task."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    assert fresh.status == "pending"

    # Task A is blocked
    with pytest.raises(HTTPException) as exc:
        await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.execute",
                task_id=task_a,
                payload={"reason": "Blocked task A."},
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_payload_string_spoof_does_not_unblock(
    sqlite_session: AsyncSession,
) -> None:
    """v1 checked if the rejection payload contained '@miguel' or
    'operator approved' — workers control the payload, so they could
    self-unblock. v2 must not regress: string-matching payloads is not
    a valid unblock channel.
    """
    session = sqlite_session
    board, task_ids, _ = await _seed(session)
    task_id = task_ids[0]
    actor = _user_actor(session)

    # 3 rejections, each carrying '@miguel operator approved' in payload
    for _ in range(3):
        created = await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.execute",
                task_id=task_id,
                payload={
                    "reason": "Submitted with @Miguel operator approved spoof.",
                },
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
        await approvals_api.update_approval(
            approval_id=created.id,
            payload=ApprovalUpdate(status="rejected"),
            board=board,
            session=session,
            actor=actor,
        )

    # Even with spoof text in the payload, the loop guard should
    # still fire — unblock requires an authenticated unblock event.
    with pytest.raises(HTTPException) as exc:
        await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.execute",
                task_id=task_id,
                payload={
                    "reason": "Another spoof: @miguel operator approved.",
                },
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
    assert exc.value.status_code == 409
    assert "Rejection loop detected" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_approval_rejects_non_pending_status_for_all_actors(
    sqlite_session: AsyncSession,
) -> None:
    """v1→v2→v2.1 Codex review finding: ``create_approval`` is for
    submitting NEW pending requests only. Non-pending statuses must go
    through PATCH or ``/unblock``. This closes the worker self-reset
    bypass (creating ``status="approved"`` would reset the rejection
    streak) and also removes the admin footgun where a board-write human
    could accidentally reset via seed.

    Both agents and human users must receive 400 for non-pending seeds.
    """
    session = sqlite_session
    board, task_ids, gateway = await _seed(session)
    task_id = task_ids[0]
    worker = await _worker_agent(session, gateway.id, board.id)
    worker_actor = ActorContext(actor_type="agent", agent=worker)
    user_actor = _user_actor(session)

    for actor in (worker_actor, user_actor):
        # status=approved seed rejected
        with pytest.raises(HTTPException) as exc_approved:
            await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.execute",
                    task_id=task_id,
                    payload={"reason": "Seeding fake approval."},
                    confidence=100,
                    status="approved",
                ),
                board=board,
                session=session,
                actor=actor,
            )
        assert exc_approved.value.status_code == 400
        assert "create_approval only accepts status='pending'" in str(exc_approved.value.detail)

        # status=rejected seed rejected
        with pytest.raises(HTTPException) as exc_rejected:
            await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.execute",
                    task_id=task_id,
                    payload={"reason": "Seeding fake rejection."},
                    confidence=0,
                    status="rejected",
                ),
                board=board,
                session=session,
                actor=actor,
            )
        assert exc_rejected.value.status_code == 400


@pytest.mark.asyncio
async def test_multi_task_approval_blocks_only_exceeded_tasks(
    sqlite_session: AsyncSession,
) -> None:
    """Batch approval covering tasks A and B: rejecting the batch
    records rejections against BOTH task rows in ApprovalHistory. After
    3 rejection cycles, BOTH tasks must be blocked (not just the
    primary ``task_id``) because they are linked via
    ``approval_task_links``. v1 filtered only on ``Approval.task_id``
    and missed linked tasks entirely.
    """
    session = sqlite_session
    board, task_ids, _ = await _seed(session, task_count=3)
    task_a, task_b, task_c = task_ids
    actor = _user_actor(session)

    # 3 cycles of batch approval on tasks A and B — each records
    # a rejection row per linked task.
    for i in range(3):
        created = await approvals_api.create_approval(
            payload=ApprovalCreate(
                action_type="task.batch_execute",
                task_ids=[task_a, task_b],
                payload={"reason": f"Batch cycle {i + 1}."},
                confidence=80,
                status="pending",
            ),
            board=board,
            session=session,
            actor=actor,
        )
        await approvals_api.update_approval(
            approval_id=created.id,  # type: ignore[arg-type]
            payload=ApprovalUpdate(status="rejected"),
            board=board,
            session=session,
            actor=actor,
        )

    # Both task A and task B must be blocked on a new single-task
    # submission, because each accumulated 3 rejection rows.
    for blocked_task_id in (task_a, task_b):
        with pytest.raises(HTTPException) as exc:
            await approvals_api.create_approval(
                payload=ApprovalCreate(
                    action_type="task.execute",
                    task_id=blocked_task_id,
                    payload={"reason": "Should be blocked."},
                    confidence=80,
                    status="pending",
                ),
                board=board,
                session=session,
                actor=actor,
            )
        assert (
            exc.value.status_code == 409
        ), f"Task {blocked_task_id} should be blocked after 3 batch rejections"

    # Unrelated task C is untouched and must still be submittable.
    fresh_c = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_c,
            payload={"reason": "Unrelated."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    assert fresh_c.status == "pending"


@pytest.mark.asyncio
async def test_history_actor_provenance_columns_are_written(
    sqlite_session: AsyncSession,
) -> None:
    """Regression: ensure the actor columns on ``approval_history`` are
    populated correctly for user vs agent actors. This is the key
    provenance property that makes the unblock channel non-spoofable.
    """
    from sqlmodel import select

    from app.models.approval_history import ApprovalHistory

    session = sqlite_session
    board, task_ids, gateway = await _seed(session)
    task_id = task_ids[0]
    user_actor = _user_actor(session)
    lead = await _lead_agent(session, gateway.id, board.id)
    lead_actor = ActorContext(actor_type="agent", agent=lead)

    # User creates + lead rejects
    created = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "User submission."},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=user_actor,
    )
    await approvals_api.update_approval(
        approval_id=created.id,  # type: ignore[arg-type]
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=lead_actor,
    )

    events = (
        await session.exec(
            select(ApprovalHistory)
            .where(ApprovalHistory.approval_id == created.id)
            .order_by(ApprovalHistory.created_at)  # type: ignore[arg-type]
        )
    ).all()
    assert len(events) == 2, "Expected submitted + rejected events"

    submitted, rejected = events
    assert submitted.event_type == "submitted"
    assert submitted.actor_type == "user"
    assert submitted.actor_user_id == user_actor.user.id  # type: ignore[union-attr]
    assert submitted.actor_agent_id is None

    assert rejected.event_type == "rejected"
    assert rejected.actor_type == "agent"
    assert rejected.actor_agent_id == lead.id
    assert rejected.actor_user_id is None


@pytest.mark.asyncio
async def test_reopen_cycle_counts_as_distinct_rejections(
    sqlite_session: AsyncSession,
) -> None:
    """Reopening a single approval row and rejecting it multiple times
    must accumulate rejection events in ApprovalHistory, since the v1
    bug was that reopening reused the same Approval row and hid history.
    """
    session = sqlite_session
    board, task_ids, _ = await _seed(session)
    task_id = task_ids[0]
    actor = _user_actor(session)

    # Cycle 1: create + reject
    a = await approvals_api.create_approval(
        payload=ApprovalCreate(
            action_type="task.execute",
            task_id=task_id,
            payload={"reason": "Cycle 1"},
            confidence=80,
            status="pending",
        ),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=a.id,
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=actor,
    )
    # Cycle 2: reopen same row + reject
    await approvals_api.update_approval(
        approval_id=a.id,
        payload=ApprovalUpdate(status="pending"),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=a.id,
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=actor,
    )
    # Cycle 3: reopen same row + reject
    await approvals_api.update_approval(
        approval_id=a.id,
        payload=ApprovalUpdate(status="pending"),
        board=board,
        session=session,
        actor=actor,
    )
    await approvals_api.update_approval(
        approval_id=a.id,
        payload=ApprovalUpdate(status="rejected"),
        board=board,
        session=session,
        actor=actor,
    )

    # 4th reopen must now be blocked by the loop guard
    with pytest.raises(HTTPException) as exc:
        await approvals_api.update_approval(
            approval_id=a.id,
            payload=ApprovalUpdate(status="pending"),
            board=board,
            session=session,
            actor=actor,
        )
    assert exc.value.status_code == 409
    assert "Rejection loop detected" in str(exc.value.detail)
