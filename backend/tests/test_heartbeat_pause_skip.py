# ruff: noqa: INP001
"""Tests for paused-board skip in heartbeat sweep + watchdog.

Background: ``POST /api/mission-control/boards/{id}/pause`` writes
``board_pause_states.is_paused = TRUE``. Before this fix the sweep and
watchdog ignored that flag and continued waking/repairing the agents,
so the operator-visible "Pause" toggle did not actually silence them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.services.openclaw.heartbeat_sweep as heartbeat_sweep
import app.services.openclaw.heartbeat_watchdog as heartbeat_watchdog
from app.core.time import utcnow
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.agents import Agent

# ---------------------------------------------------------------------
# Shared fake session
# ---------------------------------------------------------------------


@dataclass
class _FakeExecResult:
    rows: list[Any]
    rowcount: int = 0

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        return self.rows[0] if self.rows else 0


@dataclass
class _FakeSession:
    """Session double supporting ``.exec`` (SQLModel selects) and
    ``.execute`` (raw text for board_pause_states)."""

    agents: list[Agent] = field(default_factory=list)
    paused_board_ids: set[UUID] = field(default_factory=set)
    repair_events: list[AgentHeartbeatRepairEvent] = field(default_factory=list)
    update_rowcounts: list[int] = field(default_factory=list)
    commits: int = 0
    _update_idx: int = 0

    async def exec(self, statement: Any) -> _FakeExecResult:
        name = type(statement).__name__
        if name in {"Update", "UpdateBase"}:
            if self._update_idx < len(self.update_rowcounts):
                rowcount = self.update_rowcounts[self._update_idx]
            else:
                rowcount = 1
            self._update_idx += 1
            return _FakeExecResult(rows=[], rowcount=rowcount)
        return _FakeExecResult(rows=list(self.agents))

    async def execute(self, statement: Any) -> _FakeExecResult:
        # The only ``execute`` caller exercised here is
        # ``_fetch_paused_board_ids`` selecting board_id rows.
        return _FakeExecResult(rows=[(bid,) for bid in self.paused_board_ids])

    def add(self, value: Any) -> None:
        if isinstance(value, AgentHeartbeatRepairEvent):
            self.repair_events.append(value)

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------
# Helper: _fetch_paused_board_ids
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_paused_board_ids_returns_paused_set() -> None:
    paused = {uuid4(), uuid4()}
    session = _FakeSession(paused_board_ids=paused)

    result = await heartbeat_sweep._fetch_paused_board_ids(session)  # type: ignore[arg-type]

    assert result == paused


@pytest.mark.asyncio
async def test_fetch_paused_board_ids_empty_when_no_rows() -> None:
    session = _FakeSession()

    result = await heartbeat_sweep._fetch_paused_board_ids(session)  # type: ignore[arg-type]

    assert result == set()


# ---------------------------------------------------------------------
# Sweep: paused-board agents must not be woken
# ---------------------------------------------------------------------


def _overdue_agent(*, board_id: UUID | None) -> Agent:
    now = utcnow()
    return Agent(
        id=uuid4(),
        gateway_id=uuid4(),
        board_id=board_id,
        name="Supervisor",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=now - timedelta(minutes=10),
        last_seen_at=now - timedelta(minutes=15),
        wake_attempts=0,
    )


@pytest.mark.asyncio
async def test_sweep_skips_overdue_agent_on_paused_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused_board = uuid4()
    agent = _overdue_agent(board_id=paused_board)
    session = _FakeSession(agents=[agent], paused_board_ids={paused_board})

    @asynccontextmanager
    async def _fake_maker():
        yield session

    wake_calls: list[UUID] = []

    async def _fake_wake(**kwargs: Any) -> bool:
        wake_calls.append(kwargs["agent"].id)
        return True

    monkeypatch.setattr(heartbeat_sweep, "async_session_maker", _fake_maker)
    monkeypatch.setattr(heartbeat_sweep, "_try_deliver_heartbeat_wake", _fake_wake)

    report = await heartbeat_sweep.sweep_once()

    assert wake_calls == []
    assert report["woke"] == 0
    assert report["paused_skipped"] == 1


@pytest.mark.asyncio
async def test_sweep_wakes_overdue_agent_on_unpaused_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check: pause-skip must not bleed onto unpaused boards.

    ``board_id=None`` short-circuits the Board lookup inside sweep_once
    so we only exercise the pause-set membership check, not the wider
    lifecycle wiring.
    """

    agent = _overdue_agent(board_id=None)
    session = _FakeSession(agents=[agent])

    @asynccontextmanager
    async def _fake_maker():
        yield session

    wake_calls: list[UUID] = []

    async def _fake_wake(**kwargs: Any) -> bool:
        wake_calls.append(kwargs["agent"].id)
        return True

    async def _fake_gateway_first(_session: Any) -> Any:
        return SimpleNamespace(id=agent.gateway_id)

    monkeypatch.setattr(heartbeat_sweep, "async_session_maker", _fake_maker)
    monkeypatch.setattr(heartbeat_sweep, "_try_deliver_heartbeat_wake", _fake_wake)
    monkeypatch.setattr(
        heartbeat_sweep.Gateway,
        "objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=_fake_gateway_first)),
        raising=False,
    )

    report = await heartbeat_sweep.sweep_once()

    assert wake_calls == [agent.id]
    assert report["woke"] == 1
    assert report["paused_skipped"] == 0


# ---------------------------------------------------------------------
# Watchdog: paused-board null-deadline agents must not be repaired
# ---------------------------------------------------------------------


async def _fake_count_by_agent(
    session: _FakeSession,
    *,
    since: Any,
) -> dict[UUID, int]:
    return {}


@pytest.mark.asyncio
async def test_watchdog_skips_null_deadline_agent_on_paused_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused_board = uuid4()
    now = utcnow()
    agent = Agent(
        id=uuid4(),
        gateway_id=uuid4(),
        board_id=paused_board,
        name="Supervisor",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSession(agents=[agent], paused_board_ids={paused_board})

    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )

    report = await heartbeat_watchdog.sweep_null_deadlines_once(session)  # type: ignore[arg-type]

    assert report.total_scanned == 0
    assert report.repaired == 0
    assert len(session.repair_events) == 0
