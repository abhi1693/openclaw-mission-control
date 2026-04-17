# ruff: noqa: INP001
"""Unit tests for the I7 heartbeat deadline watchdog.

Covers amendment section A.1 from
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``:

- null-deadline online agents get a repaired deadline derived from their
  heartbeat_config.every + grace, with a fallback to the provisioning
  default when config is absent or malformed
- a forensic ``AgentHeartbeatRepairEvent`` row is emitted per repair
- the 1h-3x repeat-repair condition triggers a WARN-level alert log
- non-online agents and agents with a non-null deadline are ignored
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.time import utcnow
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.agents import Agent
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
)
from app.services.openclaw.heartbeat_watchdog import (
    REPAIR_REASON_NULL_DEADLINE,
    REPEAT_REPAIR_ALERT_THRESHOLD,
    _parse_heartbeat_interval,
    compute_repair_deadline,
    sweep_null_deadlines_once,
)


# --- pure function tests --------------------------------------------------


def test_parse_interval_minutes() -> None:
    assert _parse_heartbeat_interval("10m") == timedelta(minutes=10)


def test_parse_interval_seconds() -> None:
    assert _parse_heartbeat_interval("45s") == timedelta(seconds=45)


def test_parse_interval_hours() -> None:
    assert _parse_heartbeat_interval("2h") == timedelta(hours=2)


def test_parse_interval_disabled_returns_zero() -> None:
    assert _parse_heartbeat_interval("0m") == timedelta(0)


def test_parse_interval_empty_uses_default_10m() -> None:
    # DEFAULT_HEARTBEAT_CONFIG says "every: 10m"
    assert _parse_heartbeat_interval(None) == timedelta(minutes=10)
    assert _parse_heartbeat_interval("") == timedelta(minutes=10)


def test_parse_interval_malformed_uses_default_10m() -> None:
    assert _parse_heartbeat_interval("bogus") == timedelta(minutes=10)
    assert _parse_heartbeat_interval("5x") == timedelta(minutes=10)


def test_compute_deadline_uses_config_plus_grace() -> None:
    now = datetime(2026, 4, 17, 12, 0, 0)
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
    )
    expected = now + timedelta(minutes=5) + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
    assert compute_repair_deadline(agent, now=now) == expected


def test_compute_deadline_falls_back_when_config_empty() -> None:
    now = datetime(2026, 4, 17, 12, 0, 0)
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config=None,
    )
    assert compute_repair_deadline(agent, now=now) == now + CHECKIN_DEADLINE_AFTER_WAKE


def test_compute_deadline_falls_back_when_heartbeat_disabled() -> None:
    # A config of "every: 0m" means no heartbeat; watchdog must still set
    # some deadline rather than returning now. Fall through to
    # CHECKIN_DEADLINE_AFTER_WAKE.
    now = datetime(2026, 4, 17, 12, 0, 0)
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "0m"},
    )
    assert compute_repair_deadline(agent, now=now) == now + CHECKIN_DEADLINE_AFTER_WAKE


# --- fake-session sweep integration tests ---------------------------------


@dataclass
class _FakeExecResult:
    """SQLAlchemy-compatible wrapper used by ``session.exec(...).all()``."""

    rows: list[Any]

    def all(self) -> list[Any]:
        return self.rows

    def one(self) -> Any:
        if not self.rows:
            return 0
        return self.rows[0]


@dataclass
class _FakeSweepSession:
    """Minimal AsyncSession stand-in sufficient for the watchdog sweep.

    Captures inserted rows so tests can assert the forensic event shape
    without standing up a real DB. ``_count_recent_repairs`` is patched
    on the module to read from ``repair_events`` directly.
    """

    agents: list[Agent]
    commits: int = 0
    added: list[Any] = field(default_factory=list)
    repair_events: list[AgentHeartbeatRepairEvent] = field(default_factory=list)

    async def exec(self, _statement: Any) -> _FakeExecResult:
        # The watchdog issues one select-agents statement per sweep. The
        # count query is patched on the module; this method only has to
        # serve the agent fetch.
        return _FakeExecResult(rows=list(self.agents))

    def add(self, value: Any) -> None:
        self.added.append(value)
        if isinstance(value, AgentHeartbeatRepairEvent):
            self.repair_events.append(value)

    async def commit(self) -> None:
        self.commits += 1


async def _fake_count(
    session: _FakeSweepSession,
    *,
    agent_id: UUID,
    since: datetime,
) -> int:
    return sum(
        1
        for event in session.repair_events
        if event.agent_id == agent_id and event.created_at >= since
    )


@pytest.mark.asyncio
async def test_sweep_repairs_online_null_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical happy path: repair + emit forensic row."""

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        wake_attempts=2,
        last_seen_at=now - timedelta(minutes=7),
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs",
        _fake_count,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]

    assert report.total_scanned == 1
    assert report.repaired == 1
    assert report.alerts == 0
    assert session.commits == 1
    assert len(session.repair_events) == 1

    event = session.repair_events[0]
    assert event.agent_id == agent.id
    assert event.prev_deadline is None
    assert event.wake_attempts == 2
    assert event.repair_reason == REPAIR_REASON_NULL_DEADLINE
    expected_new = now + timedelta(minutes=5) + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
    assert abs((event.new_deadline - expected_new).total_seconds()) < 2
    assert agent.checkin_deadline_at == event.new_deadline
    assert event.elapsed_since_last_seen_seconds is not None
    assert 400 < event.elapsed_since_last_seen_seconds < 450


@pytest.mark.asyncio
async def test_sweep_ignores_non_online_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="offline",
        checkin_deadline_at=None,
    )
    # The real SELECT filters by status; simulate by giving fake session
    # an empty list (fake exec ignores the statement's WHERE clauses).
    session = _FakeSweepSession(agents=[])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs",
        _fake_count,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.total_scanned == 0
    assert len(session.repair_events) == 0
    assert agent.checkin_deadline_at is None


@pytest.mark.asyncio
async def test_sweep_triggers_alert_at_repeat_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an agent has been repaired 2 times within 1h, this repair
    (the 3rd) flips the alert flag to True."""

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
    )
    prior_events = [
        AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            repair_reason=REPAIR_REASON_NULL_DEADLINE,
            new_deadline=now - timedelta(minutes=40),
            wake_attempts=0,
            created_at=now - timedelta(minutes=40),
        ),
        AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            repair_reason=REPAIR_REASON_NULL_DEADLINE,
            new_deadline=now - timedelta(minutes=15),
            wake_attempts=0,
            created_at=now - timedelta(minutes=15),
        ),
    ]
    session = _FakeSweepSession(agents=[agent], repair_events=list(prior_events))
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs",
        _fake_count,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]

    assert report.repaired == 1
    assert report.alerts == 1
    assert report.outcomes[0].alert_triggered is True
    assert report.outcomes[0].repeat_count_1h >= REPEAT_REPAIR_ALERT_THRESHOLD


@pytest.mark.asyncio
async def test_sweep_does_not_alert_on_first_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single repair must not trigger the 3-in-1h alert."""

    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs",
        _fake_count,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]

    assert report.repaired == 1
    assert report.alerts == 0
    assert report.outcomes[0].alert_triggered is False
    assert report.outcomes[0].repeat_count_1h == 1
