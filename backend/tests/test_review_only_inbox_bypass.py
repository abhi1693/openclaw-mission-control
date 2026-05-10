# ruff: noqa: INP001
"""Review-only tasks must never enter `inbox` — they have no
implementation phase, so the worker→reviewer pipeline doesn't apply.
Without this guarantee, neither lead nor worker can perform
`inbox→review` (lead-status-gate, comment-required, pipeline-events
all reject), and the only escape is a manual operator OperatorDecision
resolution. The fix: review_only tasks are created in `review`
directly, and PATCHes that recategorize an inbox task to review_only
auto-advance.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import agent as agent_api
from app.api import tasks as tasks_api
from app.api.deps import ActorContext
from app.core.agent_auth import AgentAuthContext
from app.core.auth import AuthContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.tasks import TaskCreate, TaskRead, TaskUpdate


async def _user_actor(session: AsyncSession) -> ActorContext:
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    await session.flush()
    return ActorContext(actor_type="user", user=user)


async def _user_actor_with_board_write(
    session: AsyncSession,
    board: Board,
) -> ActorContext:
    """User actor with org-owner membership on ``board``'s organization,
    so user-route PATCHes pass ``_require_task_user_write_access``."""
    actor = await _user_actor(session)
    assert actor.user is not None
    session.add(
        OrganizationMember(
            organization_id=board.organization_id,
            user_id=actor.user.id,
            role="owner",
            all_boards_read=True,
            all_boards_write=True,
        ),
    )
    await session.commit()
    return actor


async def _seed_board_with_lead(session: AsyncSession) -> tuple[Board, Agent]:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{board_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gw",
            url="ws://example/ws",
            workspace_root="/tmp/wks",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        name="b",
        slug=f"b-{board_id.hex[:6]}",
    )
    session.add(board)
    lead = Agent(
        id=uuid4(),
        board_id=board_id,
        gateway_id=gateway_id,
        name="Lead",
        is_board_lead=True,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(board)
    await session.refresh(lead)
    return board, lead


@pytest.mark.asyncio
async def test_user_route_create_review_only_starts_in_review(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = await _user_actor(session)

    created = await tasks_api.create_task(
        payload=TaskCreate(
            title="Architect design-pass sign-off",
            review_packet_type="review_only",
            validation_target="http://example.com/preview",
            validation_target_kind="live_url",
            validation_target_scope="review",
            status="inbox",  # caller hint must be overridden
        ),
        board=board,
        session=session,
        auth=AuthContext(actor_type="user", user=actor.user),
    )
    assert created.status == "review"
    persisted = (await session.exec(select(Task).where(Task.id == created.id))).first()
    assert persisted.status == "review"


@pytest.mark.asyncio
async def test_agent_lead_route_create_review_only_starts_in_review(
    sqlite_session: AsyncSession,
) -> None:
    """The agent-lead route at agent.py:1152 also uses TaskCreate; both
    paths must enforce the same invariant."""
    session = sqlite_session
    board, lead = await _seed_board_with_lead(session)
    agent_ctx = AgentAuthContext(actor_type="agent", agent=lead)

    created = await agent_api.create_task(
        payload=TaskCreate(
            title="QA-E2E final acceptance pass",
            review_packet_type="review_only",
            validation_target="http://example.com/preview",
            validation_target_kind="live_url",
            validation_target_scope="review",
        ),
        board=board,
        session=session,
        agent_ctx=agent_ctx,
    )
    assert created.status == "review"


@pytest.mark.asyncio
async def test_create_non_review_only_keeps_default_inbox(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = await _user_actor(session)

    created = await tasks_api.create_task(
        payload=TaskCreate(
            title="Implement feature X",
            review_packet_type="frontend_ui",
            validation_target="http://example.com/x",
            validation_target_kind="live_url",
            validation_target_scope="review",
        ),
        board=board,
        session=session,
        auth=AuthContext(actor_type="user", user=actor.user),
    )
    assert created.status == "inbox"


@pytest.mark.asyncio
async def test_taskread_does_not_rewrite_legacy_inbox_review_only(
    sqlite_session: AsyncSession,
) -> None:
    """REGRESSION GUARD: the creation rule must NOT live on TaskBase
    (which TaskRead inherits at schemas/tasks.py:433). If it did,
    serializing an existing legacy review_only+inbox row would report
    status='review' to API clients, while the DB row stays inbox —
    breaking list filters at tasks.py:2508-2511 (DB-side filter on
    Task.status, then TaskRead serialization at tasks.py:2585).

    This test ensures TaskRead is a faithful mirror of the DB row."""
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    legacy = Task(
        id=uuid4(),
        board_id=board.id,
        title="legacy stuck task",
        status="inbox",
        review_packet_type="review_only",
    )
    session.add(legacy)
    await session.commit()
    await session.refresh(legacy)

    serialized = TaskRead.model_validate(legacy, from_attributes=True)
    assert (
        serialized.status == "inbox"
    ), f"TaskRead must mirror DB state, not rewrite it; got {serialized.status!r}"


@pytest.mark.asyncio
async def test_user_patch_to_review_only_advances_inbox_with_comment(
    sqlite_session: AsyncSession,
) -> None:
    """User-route PATCH that recategorizes inbox task to review_only
    must atomically transition status to review in the same write.
    Production incident: a8743f3a was created `mixed` then needed
    re-categorizing — a separate PATCH cycle is wasted work."""
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = await _user_actor_with_board_write(session, board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="Final acceptance",
        status="inbox",
        review_packet_type="mixed",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    updated = await tasks_api.update_task(
        payload=TaskUpdate(
            review_packet_type="review_only",
            comment="Recategorize: no implementation phase",
        ),
        task=task,
        session=session,
        actor=ActorContext(actor_type="user", user=actor.user),
    )
    # Both assertions matter: recat applied AND auto-advance fired.
    # One without the other = different bug class.
    assert updated.review_packet_type == "review_only"
    assert updated.status == "review"


@pytest.mark.asyncio
async def test_user_patch_review_only_inbox_to_review_with_comment(
    sqlite_session: AsyncSession,
) -> None:
    """User-route PATCH that explicitly moves a review_only inbox task
    to review with a comment must succeed — operator should not need
    the OperatorDecision dance for review_only."""
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = await _user_actor_with_board_write(session, board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="Stuck review-only",
        status="inbox",
        review_packet_type="review_only",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    updated = await tasks_api.update_task(
        payload=TaskUpdate(
            status="review",
            comment="operator unblock: review-only path",
        ),
        task=task,
        session=session,
        actor=ActorContext(actor_type="user", user=actor.user),
    )
    assert updated.status == "review"


@pytest.mark.asyncio
async def test_lead_patch_review_only_inbox_to_review(
    sqlite_session: AsyncSession,
) -> None:
    """Lead-path narrow exception: when target task is review_only,
    lead can perform inbox→review. Without this exception (Codex
    finding), the plan only fixes the operator path and leads still
    need operator help — half the failure mode remains.

    Note: lead PATCH disallows the ``comment`` field (see
    ``_validate_lead_update_request`` at tasks.py:4482); leads post via
    the comments endpoint, then PATCH status separately. The plan's
    narrow exception in ``_lead_apply_status`` does not require
    comment — it keys on ``review_packet_type='review_only'`` alone."""
    session = sqlite_session
    board, lead = await _seed_board_with_lead(session)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="Track F design-pass",
        status="inbox",
        review_packet_type="review_only",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    updated = await tasks_api.update_task(
        payload=TaskUpdate(status="review"),
        task=task,
        session=session,
        actor=ActorContext(actor_type="agent", agent=lead),
    )
    assert updated.status == "review"


@pytest.mark.asyncio
async def test_patch_review_only_without_comment_with_required_flag(
    sqlite_session: AsyncSession,
) -> None:
    """If board.comment_required_for_review=True, the auto-advance must
    still trip the comment-required gate at tasks.py:5783-5796. The
    auto-advance must NOT bypass this rule."""
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    board.comment_required_for_review = True
    session.add(board)
    await session.commit()
    actor = await _user_actor_with_board_write(session, board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="inbox",
        review_packet_type="mixed",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    with pytest.raises(HTTPException) as exc:
        await tasks_api.update_task(
            payload=TaskUpdate(review_packet_type="review_only"),  # no comment
            task=task,
            session=session,
            actor=ActorContext(actor_type="user", user=actor.user),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == "Comment is required."


@pytest.mark.asyncio
async def test_patch_review_only_blocked_by_legacy_operator_decision(
    sqlite_session: AsyncSession,
) -> None:
    """The auto-advance must respect the legacy operator_decision_required
    field on the task itself (tasks.py:767-768). If it's set, transition
    must still raise 409 task_blocked_operator_decision_required."""
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = await _user_actor_with_board_write(session, board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="inbox",
        review_packet_type="mixed",
        operator_decision_required=True,
        operator_decision_summary="awaiting policy decision",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    with pytest.raises(HTTPException) as exc:
        await tasks_api.update_task(
            payload=TaskUpdate(
                review_packet_type="review_only",
                comment="recat",
            ),
            task=task,
            session=session,
            actor=ActorContext(actor_type="user", user=actor.user),
        )
    assert exc.value.status_code == 409
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == "task_blocked_operator_decision_required"


@pytest.mark.asyncio
async def test_non_lead_agent_patch_review_only_rejected(
    sqlite_session: AsyncSession,
) -> None:
    """Non-lead agents (workers) MUST NOT be able to recategorize an
    inbox task to review_only — review-only sign-offs are operator/lead
    territory. Two gates enforce this in the non-lead path: the
    allowed-fields gate rejects `review_packet_type` first, and the
    `_AGENT_PATH_VALID_TRANSITIONS` gate would reject (inbox, review)
    as a fallback. The auto-advance does NOT widen either gate.

    This test asserts the end-state (403); regression-guards intent
    against any future contributor extending allowed-fields or
    transitions for the non-lead path.
    """
    session = sqlite_session
    board, lead = await _seed_board_with_lead(session)
    # Seed a non-lead agent (worker) on the same gateway as the lead.
    worker = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=lead.gateway_id,
        name="Worker",
        is_board_lead=False,
    )
    session.add(worker)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="inbox",
        review_packet_type="mixed",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    with pytest.raises(HTTPException) as exc:
        await tasks_api.update_task(
            payload=TaskUpdate(review_packet_type="review_only"),
            task=task,
            session=session,
            actor=ActorContext(actor_type="agent", agent=worker),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_lead_patch_recategorize_to_review_only_advances_inbox(
    sqlite_session: AsyncSession,
) -> None:
    """Lead-path symmetry with user path: when a lead PATCH provides
    `review_packet_type='review_only'` (recategorize) on an inbox task,
    the lead-status-gate's narrow exception must fire even though the
    task's CURRENT review_packet_type is still the old value (`mixed`,
    `frontend_ui`, etc.). Otherwise leads need two PATCHes for what
    operators can do in one — symmetry-broken.
    """
    session = sqlite_session
    board, lead = await _seed_board_with_lead(session)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="recat candidate",
        status="inbox",
        review_packet_type="mixed",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    updated = await tasks_api.update_task(
        payload=TaskUpdate(
            review_packet_type="review_only",
            status="review",
        ),
        task=task,
        session=session,
        actor=ActorContext(actor_type="agent", agent=lead),
    )
    assert updated.review_packet_type == "review_only"
    assert updated.status == "review"
