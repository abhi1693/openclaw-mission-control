from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import metrics as metrics_api


class _FakeSession:
    def __init__(self, exec_result: list[object]) -> None:
        self._exec_result = exec_result

    async def exec(self, _statement: object) -> list[object]:
        return self._exec_result


@pytest.mark.asyncio
async def test_resolve_dashboard_board_ids_returns_requested_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()

    async def _accessible(*_args: object, **_kwargs: object) -> list[object]:
        return [board_id]

    monkeypatch.setattr(
        metrics_api,
        "list_accessible_board_ids",
        _accessible,
    )
    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))

    resolved = await metrics_api._resolve_dashboard_board_ids(
        _FakeSession([]),
        ctx=ctx,
        board_id=board_id,
        group_id=None,
    )

    assert resolved == [board_id]


@pytest.mark.asyncio
async def test_resolve_dashboard_board_ids_rejects_inaccessible_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accessible_board_id = uuid4()
    requested_board_id = uuid4()

    async def _accessible(*_args: object, **_kwargs: object) -> list[object]:
        return [accessible_board_id]

    monkeypatch.setattr(
        metrics_api,
        "list_accessible_board_ids",
        _accessible,
    )
    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))

    with pytest.raises(HTTPException) as exc_info:
        await metrics_api._resolve_dashboard_board_ids(
            _FakeSession([]),
            ctx=ctx,
            board_id=requested_board_id,
            group_id=None,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_dashboard_board_ids_filters_by_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_a = uuid4()
    board_b = uuid4()
    group_id = uuid4()

    async def _accessible(*_args: object, **_kwargs: object) -> list[object]:
        return [board_a, board_b]

    monkeypatch.setattr(
        metrics_api,
        "list_accessible_board_ids",
        _accessible,
    )
    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))
    session = _FakeSession([board_b])

    resolved = await metrics_api._resolve_dashboard_board_ids(
        session,
        ctx=ctx,
        board_id=None,
        group_id=group_id,
    )

    assert resolved == [board_b]


@pytest.mark.asyncio
async def test_resolve_dashboard_board_ids_returns_empty_when_board_not_in_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    group_id = uuid4()

    async def _accessible(*_args: object, **_kwargs: object) -> list[object]:
        return [board_id]

    monkeypatch.setattr(
        metrics_api,
        "list_accessible_board_ids",
        _accessible,
    )
    ctx = SimpleNamespace(member=SimpleNamespace(organization_id=uuid4()))
    session = _FakeSession([])

    resolved = await metrics_api._resolve_dashboard_board_ids(
        session,
        ctx=ctx,
        board_id=board_id,
        group_id=group_id,
    )

    assert resolved == []
