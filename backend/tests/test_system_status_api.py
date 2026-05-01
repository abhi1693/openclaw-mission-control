# ruff: noqa: INP001, S101
"""Tests for the operator-facing `GET /api/v1/system/status` endpoint.

Exercises the router function in isolation with a fake session that returns
deterministic count values, plus a patched ``queue_depths`` so Redis isn't
required during the test run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api import system as system_api
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.services.organizations import OrganizationContext


@dataclass
class _CountResult:
    """Minimal stand-in for SQLAlchemy ``.exec()`` results returning a single int."""

    value: int

    def one(self) -> int:
        return self.value


class _FakeSession:
    """Session double that returns successive count values from a queue."""

    def __init__(self, counts: list[int]) -> None:
        self._counts: Iterator[int] = iter(counts)

    async def exec(self, _statement: object) -> _CountResult:
        return _CountResult(next(self._counts))


def _make_ctx() -> OrganizationContext:
    org_id = uuid4()
    return OrganizationContext(
        organization=Organization(id=org_id, name=f"org-{org_id}"),
        member=OrganizationMember(
            organization_id=org_id,
            user_id=uuid4(),
            role="owner",
        ),
    )


@pytest.mark.asyncio
async def test_get_system_status_returns_aggregated_counts() -> None:
    """Happy path: 23 agents (1 online), 1 gateway, 0 queue depth."""
    ctx = _make_ctx()
    session: Any = _FakeSession(counts=[23, 1, 1])  # total, online, gateway_total

    with patch.object(system_api, "queue_depths", return_value=(0, 0)):
        response = await system_api.get_system_status(org_ctx=ctx, session=session)

    assert response.queue.depth == 0
    assert response.queue.scheduled_depth == 0
    assert response.agents.total == 23
    assert response.agents.online == 1
    assert response.agents.offline == 22
    assert response.gateways.total == 1


@pytest.mark.asyncio
async def test_get_system_status_reports_queue_depth_separately_for_ready_and_scheduled() -> None:
    ctx = _make_ctx()
    session: Any = _FakeSession(counts=[5, 0, 0])

    with patch.object(system_api, "queue_depths", return_value=(7, 3)):
        response = await system_api.get_system_status(org_ctx=ctx, session=session)

    assert response.queue.depth == 7
    assert response.queue.scheduled_depth == 3


@pytest.mark.asyncio
async def test_get_system_status_offline_count_never_negative() -> None:
    """Online count cannot exceed total — guards against count-skew bugs."""
    ctx = _make_ctx()
    # If ``online`` ever exceeded ``total`` due to a misordered query, this
    # would silently produce a negative ``offline``. We expect total >= online
    # invariant to hold by construction here.
    session: Any = _FakeSession(counts=[5, 5, 0])

    with patch.object(system_api, "queue_depths", return_value=(0, 0)):
        response = await system_api.get_system_status(org_ctx=ctx, session=session)

    assert response.agents.total == 5
    assert response.agents.online == 5
    assert response.agents.offline == 0


@pytest.mark.asyncio
async def test_get_system_status_handles_empty_org() -> None:
    """A brand-new org with no agents or gateways returns clean zeros."""
    ctx = _make_ctx()
    session: Any = _FakeSession(counts=[0, 0, 0])

    with patch.object(system_api, "queue_depths", return_value=(0, 0)):
        response = await system_api.get_system_status(org_ctx=ctx, session=session)

    assert response.agents.total == 0
    assert response.agents.online == 0
    assert response.agents.offline == 0
    assert response.gateways.total == 0


@pytest.mark.asyncio
async def test_get_system_status_uses_configured_queue_name() -> None:
    """The queue.name in the response should reflect settings.rq_queue_name."""
    ctx = _make_ctx()
    session: Any = _FakeSession(counts=[0, 0, 0])

    with patch.object(system_api, "queue_depths", return_value=(0, 0)) as mock_depths:
        response = await system_api.get_system_status(org_ctx=ctx, session=session)

    # The router passes ``settings.rq_queue_name`` as the first positional
    # arg to queue_depths and also reflects it in the response payload.
    assert mock_depths.call_args is not None
    called_with = mock_depths.call_args.args[0]
    assert response.queue.name == called_with
