# ruff: noqa: S101
"""Validation tests for gateway-main-agent requirements on board mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import boards
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.boards import BoardUpdate


def _gateway(*, organization_id: UUID) -> Gateway:
    return Gateway(
        id=uuid4(),
        organization_id=organization_id,
        name="Main Gateway",
        url="ws://gateway.example/ws",
        workspace_root="/tmp/openclaw",
    )


class _FakeAgentQuery:
    def __init__(self, main_agent: object | None) -> None:
        self._main_agent = main_agent

    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeAgentQuery:
        return self

    async def first(self, _session: object) -> object | None:
        return self._main_agent


@dataclass
class _FakeAgentObjects:
    main_agent: object | None
    last_filter_by: dict[str, object] | None = None

    def filter_by(self, **kwargs: object) -> _FakeAgentQuery:
        self.last_filter_by = kwargs
        return _FakeAgentQuery(self.main_agent)


@pytest.mark.asyncio
async def test_require_gateway_rejects_when_gateway_has_no_main_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    gateway = _gateway(organization_id=organization_id)
    fake_objects = _FakeAgentObjects(main_agent=None)

    async def _fake_get_by_id(_session: object, _model: object, _gateway_id: object) -> Gateway:
        return gateway

    monkeypatch.setattr(boards.crud, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(boards.Agent, "objects", fake_objects)

    with pytest.raises(HTTPException) as exc_info:
        await boards._require_gateway(
            session=object(),  # type: ignore[arg-type]
            gateway_id=gateway.id,
            organization_id=organization_id,
        )

    assert exc_info.value.status_code == 422
    assert "gateway main agent" in str(exc_info.value.detail).lower()
    assert fake_objects.last_filter_by == {"gateway_id": gateway.id}


@pytest.mark.asyncio
async def test_require_gateway_accepts_when_gateway_has_main_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    gateway = _gateway(organization_id=organization_id)
    fake_objects = _FakeAgentObjects(main_agent=object())

    async def _fake_get_by_id(_session: object, _model: object, _gateway_id: object) -> Gateway:
        return gateway

    monkeypatch.setattr(boards.crud, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(boards.Agent, "objects", fake_objects)

    resolved = await boards._require_gateway(
        session=object(),  # type: ignore[arg-type]
        gateway_id=gateway.id,
        organization_id=organization_id,
    )

    assert resolved.id == gateway.id
    assert fake_objects.last_filter_by == {"gateway_id": gateway.id}


@pytest.mark.asyncio
async def test_apply_board_update_validates_current_gateway_main_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Platform",
        slug="platform",
        gateway_id=uuid4(),
    )
    payload = BoardUpdate(name="Platform X")
    calls: list[UUID] = []

    async def _fake_require_gateway(
        _session: object,
        gateway_id: object,
        *,
        organization_id: UUID | None = None,
    ) -> Gateway:
        _ = organization_id
        if not isinstance(gateway_id, UUID):
            raise AssertionError("expected UUID gateway id")
        calls.append(gateway_id)
        raise HTTPException(
            status_code=422,
            detail=boards._ERR_GATEWAY_MAIN_AGENT_REQUIRED,
        )

    async def _fake_save(_session: object, _board: Board) -> Board:
        return _board

    monkeypatch.setattr(boards, "_require_gateway", _fake_require_gateway)
    monkeypatch.setattr(boards.crud, "save", _fake_save)

    with pytest.raises(HTTPException) as exc_info:
        await boards._apply_board_update(
            payload=payload,
            session=object(),  # type: ignore[arg-type]
            board=board,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == boards._ERR_GATEWAY_MAIN_AGENT_REQUIRED
    assert calls == [board.gateway_id]
