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
                    review_packet_type="review_only",
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
async def test_non_lead_agent_cannot_move_task_to_in_progress_without_review_packet_type() -> None:
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

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="in_progress"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            assert exc.value.detail["code"] == "task_delivery_contract_incomplete"
            assert exc.value.detail["missing_fields"] == ["review_packet_type"]
            assert exc.value.detail["status"] == "in_progress"
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
                    review_packet_type="review_only",
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
async def test_non_lead_agent_cannot_move_frontend_task_to_review_without_validation_target() -> (
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
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="frontend task",
                    description="",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    in_progress_at=in_progress_at,
                    review_packet_type="frontend_ui",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="review", comment="Ready for review."),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            # Phase 1 pipeline gate fires first: frontend_ui without
            # packet_commit_sha is rejected before the delivery contract
            # gate checks for missing validation_target fields.
            assert exc.value.detail["code"] == "review_missing_commit"
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
                == "Agents can only change status or commit metadata on tasks assigned to them."
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
async def test_non_lead_agent_cannot_set_operator_decision_metadata() -> None:
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
                    payload=TaskUpdate(
                        operator_decision_required=True,
                        operator_decision_summary="Awaiting operator pricing decision.",
                    ),
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
async def test_lead_cannot_set_legacy_operator_decision_on_active_assigned_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            lead_id = uuid4()
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
                    id=lead_id,
                    name="Lead",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
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
                    title="active task",
                    description="",
                    status="in_progress",
                    assigned_agent_id=worker_id,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(
                        operator_decision_required=True,
                        operator_decision_summary="Waiting on deploy artifact choice.",
                    ),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=lead),
                )

            assert exc.value.status_code == 409
            assert isinstance(exc.value.detail, dict)
            assert exc.value.detail["code"] == "task_blocked_operator_decision_required"
            assert "structured Blocker" in exc.value.detail["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_can_set_legacy_operator_decision_on_terminal_assigned_task() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            lead_id = uuid4()
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
                    id=lead_id,
                    name="Lead",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
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
                    title="terminal assigned task",
                    description="",
                    status="done",
                    assigned_agent_id=worker_id,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (
                await session.exec(select(Task).where(col(Task.id) == task_id))
            ).first()
            assert task is not None
            lead = (
                await session.exec(select(Agent).where(col(Agent.id) == lead_id))
            ).first()
            assert lead is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    operator_decision_required=True,
                    operator_decision_summary="Compatibility flag on terminal task.",
                ),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert updated.operator_decision_required is True
            assert (
                updated.operator_decision_summary
                == "Compatibility flag on terminal task."
            )
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
                    review_packet_type="review_only",
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
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            sent: dict[str, str] = {}

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

                async def try_send_agent_message(
                    self,
                    *,
                    session_key: str,
                    config: Any,
                    agent_name: str,
                    message: str,
                    deliver: bool,
                ) -> str | None:
                    _ = config, deliver
                    sent["session_key"] = session_key
                    sent["agent_name"] = agent_name
                    sent["message"] = message
                    return None

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
            assert "END_WORK: task moved from in_progress to review" in sent["message"]
            assert "Route per lead-review-routing skill." in sent["message"]
            assert "Status: review" in sent["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_moves_review_task_to_inbox_unassigns_by_default_for_reroute(
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
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            sent: list[dict[str, str]] = []

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

                async def try_send_agent_message(
                    self,
                    *,
                    session_key: str,
                    config: Any,
                    agent_name: str,
                    message: str,
                    deliver: bool,
                ) -> str | None:
                    _ = config, deliver
                    sent.append(
                        {
                            "session_key": session_key,
                            "agent_name": agent_name,
                            "message": message,
                        },
                    )
                    return None

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
            assert reverted.assigned_agent_id is None
            worker_messages = [item for item in sent if item["session_key"] == "worker-session"]
            assert not worker_messages
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_moves_review_task_to_inbox_and_preserves_explicit_reroute_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            reroute_worker_id = uuid4()
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
                    id=reroute_worker_id,
                    name="reroute-worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    openclaw_session_id="reroute-session",
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
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            sent: list[dict[str, str]] = []

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

                async def try_send_agent_message(
                    self,
                    *,
                    session_key: str,
                    config: Any,
                    agent_name: str,
                    message: str,
                    deliver: bool,
                ) -> str | None:
                    _ = config, deliver
                    sent.append(
                        {
                            "session_key": session_key,
                            "agent_name": agent_name,
                            "message": message,
                        },
                    )
                    return None

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

            review_task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert review_task is not None
            reverted = await tasks_api.update_task(
                payload=TaskUpdate(status="inbox", assigned_agent_id=reroute_worker_id),
                task=review_task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert reverted.status == "inbox"
            assert reverted.assigned_agent_id == reroute_worker_id
            reroute_messages = [
                item for item in sent if item["session_key"] == "reroute-session"
            ]
            assert reroute_messages
            final_message = reroute_messages[-1]["message"]
            assert "TASK ASSIGNED" in final_message
            assert "CHANGES REQUESTED" not in final_message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_moves_review_task_to_rework_and_reassigns_last_worker_with_rework_message(
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
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            sent: list[dict[str, str]] = []

            class _FakeDispatch:
                def __init__(self, _session: AsyncSession) -> None:
                    pass

                async def optional_gateway_config_for_board(self, _board: Board) -> object:
                    return object()

                async def try_send_agent_message(
                    self,
                    *,
                    session_key: str,
                    config: Any,
                    agent_name: str,
                    message: str,
                    deliver: bool,
                ) -> str | None:
                    _ = config, deliver
                    sent.append(
                        {
                            "session_key": session_key,
                            "agent_name": agent_name,
                            "message": message,
                        },
                    )
                    return None

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
                payload=TaskUpdate(status="rework"),
                task=review_task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert reverted.status == "rework"
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
                    review_packet_type="review_only",
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
                    review_packet_type="review_only",
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


@pytest.mark.asyncio
async def test_lead_assignment_and_in_progress_wakes_assignee_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_send_agent_task_message(**_: Any) -> str | None:
        return None

    monkeypatch.setattr(tasks_api, "_send_agent_task_message", _fake_send_agent_task_message)

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            lead_id = uuid4()
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
                    id=lead_id,
                    name="lead",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                    openclaw_session_id="session-lead",
                ),
            )
            session.add(
                Agent(
                    id=worker_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="session-worker",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="assignment wake",
                    description="",
                    status="inbox",
                    assigned_agent_id=None,
                    # Phase IV §I2: now that the lead path also enforces
                    # delivery-contract after setattr (parity with
                    # ``_finalize_updated_task``), a PATCH to
                    # ``in_progress`` without ``review_packet_type`` 409s
                    # on the contract gate. Seed the field so this test
                    # exercises the wake behaviour, not the contract.
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(assigned_agent_id=worker_id, status="in_progress"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == worker_id

            reloaded_worker = (
                await session.exec(select(Agent).where(col(Agent.id) == worker_id))
            ).first()
            assert reloaded_worker is not None
            assert reloaded_worker.status == "online"
            assert reloaded_worker.last_seen_at is not None

            wake_events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.assignee_woken"),
                )
            ).all()
            assert len(wake_events) == 1
            assert wake_events[0].message is not None
            assert "(assignment)" in wake_events[0].message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_entering_in_progress_with_existing_assignee_wakes_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_send_agent_task_message(**_: Any) -> str | None:
        return None

    monkeypatch.setattr(tasks_api, "_send_agent_task_message", _fake_send_agent_task_message)

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
                    status="offline",
                    openclaw_session_id="session-worker",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="status wake",
                    description="",
                    status="inbox",
                    assigned_agent_id=worker_id,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            worker = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert worker is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="in_progress"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=worker),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == worker_id

            reloaded_worker = (
                await session.exec(select(Agent).where(col(Agent.id) == worker_id))
            ).first()
            assert reloaded_worker is not None
            assert reloaded_worker.status == "online"
            assert reloaded_worker.last_seen_at is not None

            wake_events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.assignee_woken"),
                )
            ).all()
            assert len(wake_events) == 1
            assert wake_events[0].message is not None
            assert "(status_in_progress)" in wake_events[0].message
    finally:
        await engine.dispose()


# --- Transition state machine (codex-found bugs, fixed 2026-04-24) --------


@pytest.mark.asyncio
async def test_non_lead_agent_inbox_to_review_is_refused() -> None:
    """Regression for the cycle-1 bug: an agent PATCHing ``status=review``
    on an inbox task used to succeed, wiping ``in_progress_at`` and
    ``previous_in_progress_at`` both null. Now it must 403."""

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
                    title="inbox task",
                    description="",
                    status="inbox",
                    assigned_agent_id=worker_id,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="review", comment="skip in_progress"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 403
            assert "Invalid status transition" in str(exc.value.detail)

            refreshed = (
                await session.exec(select(Task).where(col(Task.id) == task_id))
            ).first()
            assert refreshed is not None
            assert refreshed.status == "inbox"
            assert refreshed.in_progress_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_rework_to_review_is_refused() -> None:
    """Codex finding D: ``rework → review`` was the same class of bug as
    inbox→review. Agents must re-enter ``in_progress`` before review."""

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
                    title="rework task",
                    description="",
                    status="rework",
                    assigned_agent_id=worker_id,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            with pytest.raises(HTTPException) as exc:
                await tasks_api.update_task(
                    payload=TaskUpdate(status="review", comment="skip in_progress again"),
                    task=task,
                    session=session,
                    actor=ActorContext(actor_type="agent", agent=actor),
                )

            assert exc.value.status_code == 403
            assert "Invalid status transition" in str(exc.value.detail)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_noop_review_preserves_previous_in_progress_at() -> None:
    """Codex finding B: a no-op ``status=review`` PATCH on a task already
    in review used to wipe ``previous_in_progress_at`` by unconditionally
    running the branch's side effects. Tests the admin/user path, where
    any-from-any-to transitions are possible, including no-ops."""

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            task_id = uuid4()

            original_in_progress = utcnow()

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
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="review-status task",
                    description="",
                    status="review",
                    in_progress_at=None,
                    previous_in_progress_at=original_in_progress,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None

            # User actor (admin path) — no-op same-status PATCH must not wipe
            # previous_in_progress_at.
            await tasks_api.update_task(
                payload=TaskUpdate(status="review"),
                task=task,
                session=session,
                actor=ActorContext(actor_type="user", agent=None),
            )

            refreshed = (
                await session.exec(select(Task).where(col(Task.id) == task_id))
            ).first()
            assert refreshed is not None
            assert refreshed.previous_in_progress_at == original_in_progress
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_inbox_to_in_progress_shortcut_stamps_in_progress_at() -> None:
    """Codex finding A: when a lead uses the assignment-and-start
    shortcut (``status=in_progress`` + ``assigned_agent_id`` on an inbox
    task), the code used to set the status without stamping
    ``in_progress_at``. Cycle-time truth downstream was then lost."""

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            lead_id = uuid4()
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
                    id=lead_id,
                    name="Lead",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                ),
            )
            session.add(
                Agent(
                    id=worker_id,
                    name="Worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="fresh inbox task",
                    description="",
                    status="inbox",
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    status="in_progress",
                    assigned_agent_id=worker_id,
                ),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == worker_id
            assert updated.in_progress_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_agent_noop_in_progress_still_claims_unowned_task() -> None:
    """Codex review 2026-04-24 (second pass): a no-op
    ``status=in_progress`` PATCH on an already-in_progress, unowned
    task must still set ``assigned_agent_id = actor.agent.id``. The
    public API contract at the top of ``_apply_non_lead_agent_task_rules``
    advertises "agents may claim unassigned tasks by updating
    status". An over-broad no-op early return would skip that and
    make the downstream actionability gate 409 on owner-less
    actionable tasks."""

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            worker_id = uuid4()
            task_id = uuid4()
            original_in_progress = utcnow()

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
                    name="Worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="unowned in_progress task",
                    description="",
                    status="in_progress",
                    assigned_agent_id=None,  # unowned
                    in_progress_at=original_in_progress,
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            actor = (await session.exec(select(Agent).where(col(Agent.id) == worker_id))).first()
            assert actor is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="in_progress", comment="Claiming."),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=actor),
            )

            assert updated.status == "in_progress"
            assert updated.assigned_agent_id == worker_id
            # original timestamp must NOT have been overwritten
            assert updated.in_progress_at == original_in_progress
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_can_patch_deploy_truth_metadata() -> None:
    """Codex finding G: leads used to be blocked from setting
    ``packet_commit_sha`` / ``packet_build_sha`` /
    ``supports_build_metadata`` because the fields were missing
    from ``_validate_lead_update_request.allowed_fields``. A lead
    approving a review-to-done promotion had to hand-edit the DB
    to stamp the SHA. Now the fields are accepted via lead PATCH."""

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
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
                    id=lead_id,
                    name="Lead",
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
                    title="review task awaiting SHA stamp",
                    description="",
                    status="review",
                    review_packet_type="review_only",
                ),
            )
            await session.commit()

            task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
            assert task is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(
                    packet_commit_sha="781c10f",
                    supports_build_metadata=True,
                ),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )

            assert updated.packet_commit_sha == "781c10f"
            assert updated.supports_build_metadata is True
    finally:
        await engine.dispose()
