"""Tests for stuck-task heartbeat sweep execution handoff."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.services.openclaw.heartbeat_sweep as heartbeat_sweep
from app.services.openclaw.gateway_rpc import GatewayConfig


@pytest.mark.asyncio
async def test_stuck_task_nudge_resets_worker_session_before_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []

    async def _fake_openclaw_call(method, params=None, *, config=None, timeout=None):
        events.append((method, (params or {}).get("key", "")))
        return {"ok": True}

    class _FakeDispatch:
        async def try_send_agent_message(
            self, *, session_key, config, agent_name, message, deliver=False
        ):
            events.append(("send", session_key))
            return None

    monkeypatch.setattr(heartbeat_sweep, "openclaw_call", _fake_openclaw_call, raising=False)
    session_key = "agent:mc-worker:main"
    config = GatewayConfig(url="ws://gateway.example/ws", token="tok")

    result = await heartbeat_sweep._send_stuck_task_execution_nudge(
        dispatch=_FakeDispatch(),
        session_key=session_key,
        config=config,
        agent_name="Programmer-Frontend",
        message="SWEEP: work the assigned task.",
    )

    assert result is None
    assert events[:2] == [
        ("sessions.reset", session_key),
        ("send", session_key),
    ]


def test_stuck_task_nudge_candidate_skips_operator_blocked_tasks() -> None:
    task = SimpleNamespace(operator_decision_required=True, assigned_agent_id=uuid4())

    assert heartbeat_sweep._stuck_task_nudge_candidate(
        task,
        attempted_agent_ids=set(),
        blocked_by_task_ids=[],
    ) is False


def test_stuck_task_nudge_candidate_limits_to_one_task_per_agent() -> None:
    agent_id = uuid4()
    task = SimpleNamespace(operator_decision_required=False, assigned_agent_id=agent_id)

    assert heartbeat_sweep._stuck_task_nudge_candidate(
        task,
        attempted_agent_ids={str(agent_id)},
        blocked_by_task_ids=[],
    ) is False


def test_stuck_task_nudge_candidate_skips_dependency_blocked_tasks() -> None:
    task = SimpleNamespace(operator_decision_required=False, assigned_agent_id=uuid4())

    assert heartbeat_sweep._stuck_task_nudge_candidate(
        task,
        attempted_agent_ids=set(),
        blocked_by_task_ids=[uuid4()],
    ) is False
