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
    REPEAT_REPAIR_ALERT_THRESHOLD,
    RepairReason,
    compute_repair_deadline,
    sweep_null_deadlines_once,
)


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
    """``parse_every_to_seconds`` rejects ``"0m"``; the watchdog must still
    set a concrete deadline rather than leaving the agent null. Fall
    through to ``CHECKIN_DEADLINE_AFTER_WAKE``."""

    now = datetime(2026, 4, 17, 12, 0, 0)
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "0m"},
    )
    assert compute_repair_deadline(agent, now=now) == now + CHECKIN_DEADLINE_AFTER_WAKE


def test_compute_deadline_falls_back_when_config_malformed() -> None:
    """Malformed ``every`` values must not raise out of the watchdog."""

    now = datetime(2026, 4, 17, 12, 0, 0)
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "bogus"},
    )
    assert compute_repair_deadline(agent, now=now) == now + CHECKIN_DEADLINE_AFTER_WAKE


@dataclass
class _FakeExecResult:
    """SQLAlchemy-compatible wrapper used by ``session.exec(...).all()``."""

    rows: list[Any]
    rowcount: int = 0

    def all(self) -> list[Any]:
        return self.rows

    def one(self) -> Any:
        if not self.rows:
            return 0
        return self.rows[0]


@dataclass
class _FakeSweepSession:
    """Minimal AsyncSession stand-in sufficient for the watchdog sweep.

    Distinguishes SELECT statements (return agents) from UPDATE statements
    (return a rowcount). ``cas_behavior`` controls the compare-and-swap
    outcome for each agent.id: a dict mapping agent_id to ``"won"`` (the
    UPDATE affects 1 row, i.e. watchdog wins the race) or ``"lost"`` (0
    rows, i.e. a concurrent writer beat us). Default: all win.

    ``_count_recent_repairs_by_agent`` is monkeypatched on the module to
    read from ``repair_events`` directly.
    """

    agents: list[Agent]
    commits: int = 0
    repair_events: list[AgentHeartbeatRepairEvent] = field(default_factory=list)
    update_rowcounts: list[int] = field(default_factory=list)
    _update_idx: int = 0

    async def exec(self, statement: Any) -> _FakeExecResult:
        is_update = type(statement).__name__ in {"Update", "UpdateBase"}
        if is_update:
            if self._update_idx < len(self.update_rowcounts):
                rowcount = self.update_rowcounts[self._update_idx]
            else:
                rowcount = 1  # default: watchdog wins the CAS
            self._update_idx += 1
            return _FakeExecResult(rows=[], rowcount=rowcount)
        return _FakeExecResult(rows=list(self.agents), rowcount=0)

    def add(self, value: Any) -> None:
        if isinstance(value, AgentHeartbeatRepairEvent):
            self.repair_events.append(value)

    async def commit(self) -> None:
        self.commits += 1


async def _fake_count_by_agent(
    session: _FakeSweepSession,
    *,
    since: datetime,
) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    for event in session.repair_events:
        if event.created_at >= since:
            counts[event.agent_id] = counts.get(event.agent_id, 0) + 1
    return counts


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
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
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
    assert event.repair_reason == RepairReason.NULL_DEADLINE_ON_ONLINE
    expected_new = now + timedelta(minutes=5) + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
    assert abs((event.new_deadline - expected_new).total_seconds()) < 2
    # The agent row is updated via a raw SQL UPDATE (compare-and-swap),
    # so the Python instance attribute does not auto-sync — that is
    # correct prod behavior. The forensic event is the durable record.
    assert event.elapsed_since_last_seen_seconds is not None
    assert 2300 < event.elapsed_since_last_seen_seconds < 2500


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
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
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
        last_seen_at=now - timedelta(minutes=40),
    )
    prior_events = [
        AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            repair_reason=RepairReason.NULL_DEADLINE_ON_ONLINE,
            new_deadline=now - timedelta(minutes=40),
            wake_attempts=0,
            created_at=now - timedelta(minutes=40),
        ),
        AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            repair_reason=RepairReason.NULL_DEADLINE_ON_ONLINE,
            new_deadline=now - timedelta(minutes=15),
            wake_attempts=0,
            created_at=now - timedelta(minutes=15),
        ),
    ]
    session = _FakeSweepSession(agents=[agent], repair_events=list(prior_events))
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
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

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]

    assert report.repaired == 1
    assert report.alerts == 0
    assert report.outcomes[0].alert_triggered is False
    assert report.outcomes[0].repeat_count_1h == 1


# --- new filter + race-skip tests (Codex review fixes) -------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled_value", ["off", "none", "disabled", "0m", "0"])
async def test_sweep_skips_disabled_heartbeat_spellings(
    monkeypatch: pytest.MonkeyPatch, disabled_value: str,
) -> None:
    """Agents with explicitly-disabled heartbeat must not be repaired.

    All five disabled spellings are legitimate operator configurations;
    fabricating deadlines for them would contradict operator intent.
    """

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": disabled_value},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.total_scanned == 0
    assert report.repaired == 0
    assert len(session.repair_events) == 0


@pytest.mark.asyncio
async def test_sweep_skips_recently_active_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null deadline with a fresh last_seen_at is a transient lifecycle state.

    Normal wake=False template syncs leave the deadline null briefly;
    the next heartbeat restores it. Repairing inside that window would
    generate false-positive forensic events (Codex HIGH finding #1).
    """

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=3),
    )
    session = _FakeSweepSession(agents=[agent])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.total_scanned == 0
    assert report.repaired == 0
    assert len(session.repair_events) == 0


@pytest.mark.asyncio
async def test_sweep_skips_on_concurrent_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAS UPDATE returns 0 rows when another writer beat us to it.

    A real heartbeat committing between the SELECT and the watchdog's
    UPDATE would cause checkin_deadline_at to no longer be null. The
    conditional UPDATE fires zero rows; the watchdog must not emit a
    forensic event for an agent it did not actually mutate (Codex HIGH
    finding #2).
    """

    now = utcnow()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent], update_rowcounts=[0])
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.total_scanned == 1
    assert report.repaired == 0
    assert len(session.repair_events) == 0
    assert session.commits == 0
    assert report.outcomes[0].action == "skipped"
    assert report.outcomes[0].reason == "concurrent-write-won"


# --------------------------------------------------------------------
# Part E.1: models.authStatus snapshot capture on repair rows
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_event_captures_auth_status_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the gateway responds to ``models.authStatus``, the snapshot
    is stamped verbatim on the repair event row."""

    now = utcnow()
    gateway_id = uuid4()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        gateway_id=gateway_id,
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent])
    snapshot = {
        "providers": [
            {"name": "anthropic", "oauth": {"expired": False}, "rate_limit": "ok"},
            {"name": "openai", "oauth": {"expired": True}},
        ],
        "generated_at": now.isoformat(),
    }

    async def _fake_auth_status_fetch(
        session: Any,  # noqa: ARG001 — matches signature
        *,
        gateway_ids: set[UUID],
    ) -> dict[UUID, dict[str, Any] | None]:
        assert gateway_ids == {gateway_id}
        return {gateway_id: snapshot}

    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._fetch_auth_status_by_gateway",
        _fake_auth_status_fetch,
    )

    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.repaired == 1
    assert len(session.repair_events) == 1
    event = session.repair_events[0]
    assert event.auth_status_snapshot == snapshot


@pytest.mark.asyncio
async def test_repair_event_survives_null_auth_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older gateways (<4.15) don't expose ``models.authStatus``; the
    helper returns ``None`` for those. Repair must still succeed — the
    snapshot is forensic, not a gate."""

    now = utcnow()
    gateway_id = uuid4()
    agent = Agent(
        id=uuid4(),
        name="DevOps",
        status="online",
        gateway_id=gateway_id,
        heartbeat_config={"every": "5m"},
        checkin_deadline_at=None,
        last_seen_at=now - timedelta(minutes=40),
    )
    session = _FakeSweepSession(agents=[agent])

    async def _fake_auth_status_fetch(
        session: Any,  # noqa: ARG001
        *,
        gateway_ids: set[UUID],  # noqa: ARG001
    ) -> dict[UUID, dict[str, Any] | None]:
        return {gateway_id: None}

    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._count_recent_repairs_by_agent",
        _fake_count_by_agent,
    )
    monkeypatch.setattr(
        "app.services.openclaw.heartbeat_watchdog._fetch_auth_status_by_gateway",
        _fake_auth_status_fetch,
    )

    report = await sweep_null_deadlines_once(session)  # type: ignore[arg-type]
    assert report.repaired == 1
    assert session.repair_events[0].auth_status_snapshot is None
