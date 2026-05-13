"""Tests for AgentLifecycleService.with_computed_status() and _heartbeat_offline_threshold().

Branch coverage:
  - Terminal statuses: never overridden
  - Provisioning: last_seen_at is None
  - PRIMARY path: last_heartbeat_at present -- per-agent 1.5x threshold
  - FALLBACK path: last_heartbeat_at is None -- fixed 10m window on last_seen_at
  - Threshold math for various interval formats
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.time import utcnow
from app.models.agents import Agent
from app.services.openclaw.provisioning_db import (
    AgentLifecycleService,
    _heartbeat_offline_threshold,
)


def _agent(
    *,
    status: str = "online",
    last_seen_offset_s: int | None = -30,
    last_heartbeat_offset_s: int | None = None,
    heartbeat_config: dict | None = None,
) -> Agent:
    now = utcnow()
    return Agent(
        gateway_id=uuid4(),
        name="test-agent",
        status=status,
        last_seen_at=(now + timedelta(seconds=last_seen_offset_s))
            if last_seen_offset_s is not None else None,
        last_heartbeat_at=(now + timedelta(seconds=last_heartbeat_offset_s))
            if last_heartbeat_offset_s is not None else None,
        heartbeat_config=heartbeat_config or {"every": "10m"},
    )


class TestTerminalStatuses:
    def test_deleting_not_overridden(self):
        agent = _agent(status="deleting", last_heartbeat_offset_s=-9999)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "deleting"

    def test_updating_not_overridden(self):
        agent = _agent(status="updating", last_heartbeat_offset_s=-999)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "updating"


class TestProvisioningPath:
    def test_null_last_seen_at_is_provisioning(self):
        agent = _agent(last_seen_offset_s=None, last_heartbeat_offset_s=None)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "provisioning"


class TestPrimaryHeartbeatPath:
    def test_recent_heartbeat_stays_online(self):
        agent = _agent(last_heartbeat_offset_s=-300)  # 5m ago, threshold=15m
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "online"

    def test_stale_heartbeat_goes_offline(self):
        agent = _agent(last_heartbeat_offset_s=-1200)  # 20m ago, threshold=15m
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "offline"

    def test_at_threshold_boundary_stays_online(self):
        # 899s < 900s threshold: strict > means this is NOT offline.
        # Note: -900 is intentionally avoided here because tiny test execution time
        # causes now - timestamp to exceed 900s by epsilon, making it a flaky boundary.
        agent = _agent(last_heartbeat_offset_s=-899)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "online"

    def test_one_second_past_threshold_goes_offline(self):
        # 901s > 900s threshold -> offline.
        agent = _agent(last_heartbeat_offset_s=-901)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "offline"

    def test_per_agent_threshold_30m_within(self):
        # 40m ago on 30m interval -> threshold=45m -> online
        agent = _agent(
            last_heartbeat_offset_s=-2400,
            heartbeat_config={"every": "30m"},
        )
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "online"

    def test_per_agent_threshold_30m_stale(self):
        # 50m ago on 30m interval -> threshold=45m -> offline
        agent = _agent(
            last_heartbeat_offset_s=-3000,
            heartbeat_config={"every": "30m"},
        )
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "offline"

    def test_last_seen_irrelevant_when_heartbeat_present(self):
        # last_seen 2s ago, last_heartbeat stale -> offline (heartbeat path wins)
        agent = _agent(last_seen_offset_s=-2, last_heartbeat_offset_s=-1200)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "offline"


class TestFallbackPath:
    def test_null_heartbeat_recent_seen_unchanged(self):
        agent = _agent(last_heartbeat_offset_s=None, last_seen_offset_s=-300)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "online"

    def test_null_heartbeat_stale_seen_offline(self):
        agent = _agent(last_heartbeat_offset_s=None, last_seen_offset_s=-900)
        AgentLifecycleService.with_computed_status(agent)
        assert agent.status == "offline"


class TestThresholdHelper:
    @pytest.mark.parametrize("every,expected_secs", [
        ("10m", 900),
        ("30m", 2700),
        ("1h", 5400),
        ("60s", 90),
        ("25m", 2250),
    ])
    def test_threshold_math(self, every, expected_secs):
        agent = _agent(heartbeat_config={"every": every})
        assert _heartbeat_offline_threshold(agent) == timedelta(seconds=expected_secs)

    def test_missing_config_falls_back(self):
        # Create Agent directly with heartbeat_config=None to bypass _agent()'s default.
        from uuid import uuid4 as _uuid4
        agent = Agent(gateway_id=_uuid4(), name="no-config", heartbeat_config=None)
        assert _heartbeat_offline_threshold(agent) == timedelta(minutes=10)

    def test_compound_format_falls_back(self):
        # "10m30s" is unsupported -- see docstring on _heartbeat_offline_threshold
        agent = _agent(heartbeat_config={"every": "10m30s"})
        assert _heartbeat_offline_threshold(agent) == timedelta(minutes=10)
