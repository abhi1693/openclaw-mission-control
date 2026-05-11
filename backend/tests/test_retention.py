# ruff: noqa: INP001
"""Unit tests for the Phase 0 retention purge.

Covers amendment §A.4: shadow_metric_events rows older than
``shadow_metric_retention_days`` are deleted daily; the same cutoff
applies to agent_heartbeat_repair_events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.shadow_metric_events import ShadowMetricEvent
from app.services.retention import (
    purge_heartbeat_repair_events_once,
    purge_shadow_metric_events_once,
    retention_purge_loop,
    run_retention_purge_once,
)


@dataclass
class _DeleteResult:
    rowcount: int


@dataclass
class _FakeSession:
    """AsyncSession stand-in that captures executed statements."""

    rowcounts: dict[type, int] = field(default_factory=dict)
    statements: list[Any] = field(default_factory=list)
    commits: int = 0

    async def exec(self, statement: Any) -> _DeleteResult:
        self.statements.append(statement)
        # Inspect the statement's target table and return the configured
        # rowcount for that model (keyed by model class via __table__).
        rowcount = 0
        for model_cls, count in self.rowcounts.items():
            if getattr(model_cls, "__tablename__", None) == statement.table.name:
                rowcount = count
                break
        return _DeleteResult(rowcount=rowcount)

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_purge_shadow_metric_events_returns_rowcount() -> None:
    session = _FakeSession(rowcounts={ShadowMetricEvent: 7})
    deleted = await purge_shadow_metric_events_once(
        session,  # type: ignore[arg-type]
        retention_days=90,
    )
    assert deleted == 7
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_purge_heartbeat_repair_events_returns_rowcount() -> None:
    session = _FakeSession(rowcounts={AgentHeartbeatRepairEvent: 3})
    deleted = await purge_heartbeat_repair_events_once(
        session,  # type: ignore[arg-type]
        retention_days=30,
    )
    assert deleted == 3
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_purge_uses_retention_threshold() -> None:
    """The DELETE's WHERE clause must reference created_at < now - days.

    Smoke-check by verifying the rendered SQL contains both the table
    name and a created_at comparison.
    """

    session = _FakeSession(rowcounts={ShadowMetricEvent: 0})
    await purge_shadow_metric_events_once(session, retention_days=1)  # type: ignore[arg-type]
    rendered = str(session.statements[0]).lower()
    assert "shadow_metric_events" in rendered
    assert "created_at" in rendered


@pytest.mark.asyncio
async def test_run_retention_purge_once_commits_both_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full sweep commits once with row counts from both tables."""

    import app.services.retention as retention

    session = _FakeSession(
        rowcounts={
            ShadowMetricEvent: 11,
            AgentHeartbeatRepairEvent: 4,
        }
    )

    def _maker() -> _FakeSession:
        return session

    monkeypatch.setattr(retention, "async_session_maker", _maker)

    summary = await run_retention_purge_once(retention_days=90)
    assert summary["shadow_metric_events"] == 11
    assert summary["agent_heartbeat_repair_events"] == 4
    assert session.commits == 1
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_retention_loop_runs_once_and_stops_on_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop executes one purge immediately, then waits for stop_event."""

    import app.services.retention as retention

    call_count = {"n": 0}

    async def _fake_purge(retention_days: int) -> dict[str, int]:
        call_count["n"] += 1
        return {"shadow_metric_events": 0, "agent_heartbeat_repair_events": 0}

    monkeypatch.setattr(retention, "run_retention_purge_once", _fake_purge)
    # Short-circuit the loop's long sleep so stop_event takes effect fast.
    monkeypatch.setattr(retention, "RETENTION_PURGE_INTERVAL_SECONDS", 0.01)

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(retention_purge_loop(stop_event, retention_days=7))
    await asyncio.sleep(0.05)
    stop_event.set()
    await loop_task

    assert call_count["n"] >= 1


@pytest.mark.asyncio
async def test_retention_loop_survives_iteration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single iteration exception is logged; the loop continues."""

    import app.services.retention as retention

    attempts = {"n": 0}

    async def _sometimes_failing(retention_days: int) -> dict[str, int]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("simulated iteration failure")
        return {"shadow_metric_events": 0, "agent_heartbeat_repair_events": 0}

    monkeypatch.setattr(retention, "run_retention_purge_once", _sometimes_failing)
    monkeypatch.setattr(retention, "RETENTION_PURGE_INTERVAL_SECONDS", 0.01)

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(retention_purge_loop(stop_event, retention_days=7))
    await asyncio.sleep(0.05)
    stop_event.set()
    await loop_task

    # First call raised, second completed — loop didn't die on the exception.
    assert attempts["n"] >= 2
