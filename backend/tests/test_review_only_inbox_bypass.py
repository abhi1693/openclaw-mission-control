# ruff: noqa: INP001
"""Review-only tasks must never enter `inbox` — they have no
implementation phase, so the worker→reviewer pipeline doesn't apply.

Production incident 2026-05-09: Track F (`ab91d422`) and Final
acceptance (`a8743f3a`) sat stuck in inbox; neither lead nor worker
can perform `inbox→review` (lead status gate trips, OperatorDecision
emitted, pipeline drains). The fix: review_only tasks are created in
`review` directly.

These tests are RED until `normalize_review_only_initial_status` is
called from both create_task handlers.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api import agent as agent_api
from app.api.deps import ActorContext
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User
from app.schemas.tasks import TaskCreate, TaskRead


def _user_actor(session: AsyncSession) -> ActorContext:
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    return ActorContext(actor_type="user", user=user)


async def _seed_board_with_lead(session: AsyncSession) -> tuple[Board, Agent]:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{board_id}"))
    session.add(
        Gateway(
            id=gateway_id, organization_id=org_id, name="gw",
            url="ws://example/ws", workspace_root="/tmp/wks",
        ),
    )
    board = Board(
        id=board_id, organization_id=org_id, name="b",
        slug=f"b-{board_id.hex[:6]}",
    )
    session.add(board)
    lead = Agent(
        id=uuid4(), board_id=board_id, gateway_id=gateway_id,
        name="Lead", auth_token=f"tok-{uuid4().hex}",
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
    actor = _user_actor(session)

    created = await tasks_api.create_task(
        payload=TaskCreate(
            title="Architect design-pass sign-off",
            review_packet_type="review_only",
            validation_target="http://example.com/preview",
            validation_target_kind="live_url",
            validation_target_scope="review",
            status="inbox",  # caller hint must be overridden
        ),
        board=board, session=session,
        auth=type("A", (), {"user": actor.user, "agent": None})(),
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
        board=board, session=session, agent_ctx=agent_ctx,
    )
    assert created.status == "review"


@pytest.mark.asyncio
async def test_create_non_review_only_keeps_default_inbox(
    sqlite_session: AsyncSession,
) -> None:
    session = sqlite_session
    board, _ = await _seed_board_with_lead(session)
    actor = _user_actor(session)

    created = await tasks_api.create_task(
        payload=TaskCreate(
            title="Implement feature X",
            review_packet_type="frontend_ui",
            validation_target="http://example.com/x",
            validation_target_kind="live_url",
            validation_target_scope="review",
        ),
        board=board, session=session,
        auth=type("A", (), {"user": actor.user, "agent": None})(),
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
        id=uuid4(), board_id=board.id, title="legacy stuck task",
        status="inbox", review_packet_type="review_only",
    )
    session.add(legacy)
    await session.commit()
    await session.refresh(legacy)

    serialized = TaskRead.model_validate(legacy, from_attributes=True)
    assert serialized.status == "inbox", (
        f"TaskRead must mirror DB state, not rewrite it; got {serialized.status!r}"
    )
