# ruff: noqa: INP001
"""Codex 2026-05-03 review: ``/deploy/notify`` writes pipeline events
without the agent-path status gate.

Decision: reject ``cancelled`` outright (QA-ing a dead task is
unambiguously wrong). For the other non-active statuses (``inbox``,
``rework``), record an audit activity event so operators can see if
real CI workflows fire on those statuses before tightening further.

The active statuses (``in_progress``, ``review``, ``done``) keep
silent fast-path behavior — those are the canonical webhook targets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deploy as deploy_api
from app.api.deploy import DeployNotifyPayload
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.tasks import Task
from app.services.openclaw.gateway_rpc import GatewayConfig


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def deploy_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncEngine, dict[str, object]]]:
    """Seed Dev Squad board + QA-E2E agent. Patch dispatch + session
    factory so the endpoint can run end-to-end without real gateway."""
    engine = await _make_engine()
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id=org_id, name="org"))
        session.add(
            Gateway(
                id=gateway_id, organization_id=org_id, name="gateway",
                url="ws://gateway.example/ws", workspace_root="/tmp/ws",
            ),
        )
        session.add(
            Board(
                id=board_id, organization_id=org_id, gateway_id=gateway_id,
                name="Dev Squad", slug="dev-squad",
            ),
        )
        session.add(
            Agent(
                id=agent_id, board_id=board_id, gateway_id=gateway_id,
                name="QA-E2E", openclaw_session_id="agent:qa-e2e:main",
            ),
        )
        await session.commit()

    # Patch session_maker so the endpoint reuses our in-memory engine.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_maker():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    monkeypatch.setattr(deploy_api, "async_session_maker", _session_maker)

    # Patch dispatch so try_send_agent_message no-ops without a real WS.
    sent: list[dict[str, object]] = []

    class _FakeDispatch:
        def __init__(self, session): self.session = session

        async def optional_gateway_config_for_board(self, board):
            return GatewayConfig(url="ws://gateway.example/ws")

        async def try_send_agent_message(self, **kwargs):
            sent.append(kwargs)
            return None

    monkeypatch.setattr(deploy_api, "GatewayDispatchService", _FakeDispatch)

    handles: dict[str, object] = {
        "engine": engine, "board_id": board_id, "agent_id": agent_id,
        "sent": sent,
    }
    try:
        yield engine, handles
    finally:
        await engine.dispose()


async def _seed_task(engine: AsyncEngine, *, board_id, status: str) -> Task:
    task_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Task(
            id=task_id, board_id=board_id, title=f"task-{status}",
            status=status,
        ))
        await session.commit()
        task = (await session.exec(select(Task).where(col(Task.id) == task_id))).first()
        assert task is not None
        return task


def _payload(task_id) -> DeployNotifyPayload:
    return DeployNotifyPayload(
        task_id=task_id, build_hash="rnK5F4Fe",
        deploy_target="http://192.168.2.63:3002", commit_sha="c2ba7f76",
    )


@pytest.mark.asyncio
async def test_deploy_notify_rejects_cancelled_task(
    deploy_seed: tuple[AsyncEngine, dict[str, object]],
) -> None:
    """Cancelled tasks are dead — QA-E2E dispatch + new pipeline events
    on them would pollute audit trails and trigger pointless work."""
    engine, handles = deploy_seed
    task = await _seed_task(engine, board_id=handles["board_id"], status="cancelled")

    with pytest.raises(HTTPException) as exc_info:
        await deploy_api.api_deploy_notify(payload=_payload(task.id))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "deploy_notify_task_cancelled"
    assert detail.get("current_status") == "cancelled"

    # Pipeline events must NOT have been written.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        events = list(
            await session.exec(
                select(TaskPipelineEvent).where(col(TaskPipelineEvent.task_id) == task.id),
            ),
        )
        assert events == [], (
            "rejected deploy_notify must not leave half-written pipeline events"
        )

    assert handles["sent"] == [], "no QA dispatch on a cancelled task"


@pytest.mark.asyncio
async def test_deploy_notify_records_audit_when_task_inbox(
    deploy_seed: tuple[AsyncEngine, dict[str, object]],
) -> None:
    """Inbox tasks are not the canonical webhook target. We currently
    accept the deploy_notify (preserving CI compat) but record an
    audit so operators can detect drift in their CI triggers."""
    engine, handles = deploy_seed
    task = await _seed_task(engine, board_id=handles["board_id"], status="inbox")

    response = await deploy_api.api_deploy_notify(payload=_payload(task.id))
    assert response.ok is True

    async with AsyncSession(engine, expire_on_commit=False) as session:
        audit = list(
            await session.exec(
                select(ActivityEvent)
                .where(col(ActivityEvent.task_id) == task.id)
                .where(col(ActivityEvent.event_type) == "task.deploy_notify_on_non_active_status"),
            ),
        )
        assert len(audit) == 1, (
            "inbox deploy_notify must record an audit event for operator visibility"
        )
        assert "inbox" in (audit[0].message or "")


@pytest.mark.asyncio
async def test_deploy_notify_no_audit_when_task_in_progress(
    deploy_seed: tuple[AsyncEngine, dict[str, object]],
) -> None:
    """Active statuses (in_progress, review, done) are the canonical
    targets — no audit needed, fast path stays silent."""
    engine, handles = deploy_seed
    task = await _seed_task(engine, board_id=handles["board_id"], status="in_progress")

    response = await deploy_api.api_deploy_notify(payload=_payload(task.id))
    assert response.ok is True

    async with AsyncSession(engine, expire_on_commit=False) as session:
        audit = list(
            await session.exec(
                select(ActivityEvent)
                .where(col(ActivityEvent.task_id) == task.id)
                .where(col(ActivityEvent.event_type) == "task.deploy_notify_on_non_active_status"),
            ),
        )
        assert audit == [], "in_progress deploy_notify is canonical — no audit"
