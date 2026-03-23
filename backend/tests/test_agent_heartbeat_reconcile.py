# ruff: noqa: INP001
"""Regression tests for heartbeat-driven lifecycle recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.time import utcnow
from app.models.agents import Agent
from app.schemas.agents import AgentRead
from app.services.openclaw.lifecycle_queue import QueuedAgentLifecycleReconcile
from app.services.openclaw.provisioning_db import AgentLifecycleService


@dataclass
class _FakeSession:
    added: list[object] = field(default_factory=list)
    committed: int = 0
    refreshed: list[object] = field(default_factory=list)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


@pytest.mark.asyncio
async def test_commit_heartbeat_enqueues_followup_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = AgentLifecycleService(session)  # type: ignore[arg-type]
    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        gateway_id=uuid4(),
        board_id=uuid4(),
        status="online",
        heartbeat_config={"every": "10m", "target": "last", "includeReasoning": False},
    )
    captured: list[QueuedAgentLifecycleReconcile] = []

    monkeypatch.setattr("app.services.openclaw.provisioning_db.utcnow", lambda: now)
    monkeypatch.setattr(
        "app.services.openclaw.provisioning_db.enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )
    monkeypatch.setattr(
        AgentLifecycleService,
        "record_heartbeat",
        staticmethod(lambda _session, _agent: None),
    )
    monkeypatch.setattr(
        AgentLifecycleService,
        "to_agent_read",
        classmethod(lambda cls, value: AgentRead.model_validate(value, from_attributes=True)),
    )

    result = await service.commit_heartbeat(agent=agent, status_value=None)

    assert result.last_seen_at == now
    assert agent.checkin_deadline_at == now + timedelta(minutes=11)
    assert len(captured) == 1
    assert captured[0].agent_id == agent.id
    assert captured[0].generation == agent.lifecycle_generation
    assert captured[0].expected_checkin_after == now
    assert captured[0].checkin_deadline_at == now + timedelta(minutes=11)
