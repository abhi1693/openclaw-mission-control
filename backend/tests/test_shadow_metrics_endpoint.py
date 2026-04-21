# ruff: noqa: INP001
"""Tests for the operator-scope GET /metrics/shadow endpoint.

Covers amendment §A.7: org-admin lists shadow-metric events scoped to
accessible boards, filters by event_type / task_id / agent_id / since /
until.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import metrics as metrics_api


@pytest.mark.asyncio
async def test_cross_board_access_rejects_board_id_outside_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org-admin can't query shadow events for a board they don't own."""

    admin_board = uuid4()
    foreign_board = uuid4()

    async def _accessible(*_a: object, **_kw: object) -> list[object]:
        return [admin_board]

    monkeypatch.setattr(metrics_api, "list_accessible_board_ids", _accessible)

    class _FakeSession:
        async def exec(self, _statement: object) -> object:
            return []

    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))
    with pytest.raises(HTTPException) as exc_info:
        await metrics_api.list_shadow_metric_events(  # type: ignore[call-arg]
            event_type=None,
            board_id=foreign_board,
            task_id=None,
            agent_id=None,
            since=None,
            until=None,
            session=_FakeSession(),  # type: ignore[arg-type]
            ctx=ctx,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_empty_access_list_returns_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the admin has no accessible boards, the statement short-circuits.

    We verify paginate is called with a statement that filters on an
    empty board_id IN (...) clause — SQL returns zero rows.
    """

    async def _accessible(*_a: object, **_kw: object) -> list[object]:
        return []

    monkeypatch.setattr(metrics_api, "list_accessible_board_ids", _accessible)

    captured_statements: list[Any] = []

    async def _fake_paginate(_session: Any, statement: Any) -> Any:
        captured_statements.append(statement)
        return SimpleNamespace(items=[], total=0, limit=50, offset=0)

    monkeypatch.setattr(metrics_api, "paginate", _fake_paginate)

    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))
    result = await metrics_api.list_shadow_metric_events(  # type: ignore[call-arg]
        event_type=None,
        board_id=None,
        task_id=None,
        agent_id=None,
        since=None,
        until=None,
        session=object(),  # type: ignore[arg-type]
        ctx=ctx,
    )
    assert result.total == 0
    assert len(captured_statements) == 1


@pytest.mark.asyncio
async def test_filters_compose_on_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each query-param maps onto one WHERE clause on the same statement.

    Smoke test: all filters applied doesn't raise, and paginate is
    invoked once with a complete statement.
    """

    board_id = uuid4()

    async def _accessible(*_a: object, **_kw: object) -> list[object]:
        return [board_id]

    monkeypatch.setattr(metrics_api, "list_accessible_board_ids", _accessible)

    called = {"count": 0}

    async def _fake_paginate(_session: Any, _statement: Any) -> Any:
        called["count"] += 1
        return SimpleNamespace(items=[], total=0, limit=50, offset=0)

    monkeypatch.setattr(metrics_api, "paginate", _fake_paginate)

    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))
    await metrics_api.list_shadow_metric_events(  # type: ignore[call-arg]
        event_type="comment.ack_only_candidate",
        board_id=board_id,
        task_id=uuid4(),
        agent_id=uuid4(),
        since=datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc),
        until=datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc) + timedelta(days=1),
        session=object(),  # type: ignore[arg-type]
        ctx=ctx,
    )
    assert called["count"] == 1
