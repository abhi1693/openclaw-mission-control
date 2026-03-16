from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api.deps import ActorContext
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
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
async def test_non_lead_agent_can_update_status_for_unassigned_task() -> None:
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
                    only_lead_can_change_status=False,
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

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="in_progress"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == actor_id
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
            assert (
                exc.value.detail["message"]
                == "Agents can only change status on tasks assigned to them."
            )
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


@pytest.mark.asyncio
async def test_non_lead_agent_moves_task_to_review_and_reassigns_to_lead() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            lead_id = uuid4()
            task_id = uuid4()
            in_progress_at = utcnow()

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
                Agent(
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assigned task",
                    description="",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=in_progress_at,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="review", comment="Moving to review."),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "review"
            assert updated.assigned_agent_id == lead_id
            assert updated.in_progress_at is None

            refreshed_task = (
                await session.exec(select(Task).where(col(Task.id) == task_id))
            ).first()
            assert refreshed_task is not None
            assert refreshed_task.previous_in_progress_at == in_progress_at
            assert refreshed_task.assigned_agent_id == lead_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_move_to_review_reassigns_to_lead_and_sends_review_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            lead_id = uuid4()
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
                Agent(
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                    openclaw_session_id="lead-session",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assigned task",
                    description="done and ready",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=utcnow(),
                ),
            )
            await session.commit()

            sent: dict[str, str] = {}

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

            async def _fake_send_agent_task_message(
                *,
                dispatch: Any,
                session_key: str,
                config: Any,
                agent_name: str,
                message: str,
            ) -> None:
                _ = dispatch, config
                sent["session_key"] = session_key
                sent["agent_name"] = agent_name
                sent["message"] = message
                return None

            monkeypatch.setattr(tasks_api, "GatewayDispatchService", _FakeDispatch)
            monkeypatch.setattr(
                tasks_api, "_send_agent_task_message", _fake_send_agent_task_message
            )

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="review", comment="Moving to review."),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "review"
            assert updated.assigned_agent_id == lead_id
            assert sent["session_key"] == "lead-session"
            assert sent["agent_name"] == "Lead Agent"
            assert "TASK READY FOR LEAD REVIEW" in sent["message"]
            assert "review the deliverables" in sent["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_moves_review_task_to_inbox_and_reassigns_last_worker_with_rework_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            lead_id = uuid4()
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
                    openclaw_session_id="worker-session",
                ),
            )
            session.add(
                Agent(
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                    openclaw_session_id="lead-session",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assigned task",
                    description="ready",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=utcnow(),
                ),
            )
            await session.commit()

            sent: list[dict[str, str]] = []

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

            async def _fake_send_agent_task_message(
                *,
                dispatch: Any,
                session_key: str,
                config: Any,
                agent_name: str,
                message: str,
            ) -> None:
                _ = dispatch, config
                sent.append(
                    {
                        "session_key": session_key,
                        "agent_name": agent_name,
                        "message": message,
                    },
                )
                return None

            monkeypatch.setattr(tasks_api, "GatewayDispatchService", _FakeDispatch)
            monkeypatch.setattr(
                tasks_api, "_send_agent_task_message", _fake_send_agent_task_message
            )

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            worker = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert worker is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            moved_to_review = await tasks_api.update_task(
                payload=TaskUpdate(status="review", comment="Ready for review."),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )
            assert moved_to_review.status == "review"
            assert moved_to_review.assigned_agent_id == lead_id

            session.add(
                ActivityEvent(
                    event_type="task.comment",
                    task_id=task_id,
                    agent_id=lead_id,
                    message="Please update error handling and add tests for edge cases.",
                ),
            )
            await session.commit()

            review_task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert review_task is not None
            reverted = await tasks_api.update_task(
                payload=TaskUpdate(status="inbox"),
                task=review_task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert reverted.status == "inbox"
            assert reverted.assigned_agent_id == worker_id
            worker_messages = [item for item in sent if item["session_key"] == "worker-session"]
            assert worker_messages
            final_message = worker_messages[-1]["message"]
            assert "CHANGES REQUESTED" in final_message
            assert "Please update error handling and add tests for edge cases." in final_message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_comment_in_review_without_status_does_not_reassign() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            assignee_id = uuid4()
            commentator_id = uuid4()
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
                    id=assignee_id,
                    name="assignee",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Agent(
                    id=commentator_id,
                    name="commentator",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="review task",
                    description="",
                    status="review",
                    assigned_agent_id=None,
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            commentator = (
                await session.exec(select(Agent).where(col(Agent.id) == commentator_id))
            ).first()
            assert commentator is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(comment="I can help with this."),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=commentator),
            )

            assert updated.status == "review"
            assert updated.assigned_agent_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_moves_to_review_without_comment_when_rule_disabled() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            lead_id = uuid4()
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
                    comment_required_for_review=False,
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
                Agent(
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assigned task",
                    description="",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=utcnow(),
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="review"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "review"
            assert updated.assigned_agent_id == lead_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_moves_to_review_without_comment_or_recent_comment_fails_when_rule_enabled() -> (
    None
):
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
                    comment_required_for_review=True,
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
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=utcnow(),
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="review"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 422
            assert exc.value.detail == "Comment is required."
    finally:
        await engine.dispose()
