# ruff: noqa: INP001
"""Lifecycle reconcile state helpers."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.core.time import utcnow
from app.models.agents import Agent
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN,
)
from app.services.openclaw.lifecycle_reconcile import _has_checked_in_since_wake


def _agent(*, last_seen_offset_s: int | None, last_wake_offset_s: int | None) -> Agent:
    now = utcnow()
    return Agent(
        name="reconcile-test",
        gateway_id=uuid4(),
        last_seen_at=(
            (now + timedelta(seconds=last_seen_offset_s))
            if last_seen_offset_s is not None
            else None
        ),
        last_wake_sent_at=(
            (now + timedelta(seconds=last_wake_offset_s))
            if last_wake_offset_s is not None
            else None
        ),
    )


def test_checked_in_since_wake_when_last_seen_after_wake() -> None:
    agent = _agent(last_seen_offset_s=5, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is True


def test_not_checked_in_since_wake_when_last_seen_before_wake() -> None:
    agent = _agent(last_seen_offset_s=-5, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is False


def test_not_checked_in_since_wake_when_missing_last_seen() -> None:
    agent = _agent(last_seen_offset_s=None, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is False


def test_lifecycle_convergence_policy_constants() -> None:
    assert CHECKIN_DEADLINE_AFTER_WAKE == timedelta(seconds=30)
    assert MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN == 3
