# ruff: noqa: S101
"""Unit tests for board worker-agent spawn limits."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

import app.services.openclaw.provisioning_db as agent_service
from app.schemas.agents import AgentCreate


@dataclass
class _FakeSession:
    async def exec(self, *_args: object, **_kwargs: object) -> None:
        return None


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID
    max_agents: int


@dataclass
class _AgentStub:
    id: UUID
    board_id: UUID | None
    is_board_lead: bool


@pytest.mark.asyncio
async def test_create_agent_as_lead_enforces_board_max_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = agent_service.AgentLifecycleService(_FakeSession())  # type: ignore[arg-type]

    board_id = uuid4()
    board = _BoardStub(id=board_id, gateway_id=uuid4(), max_agents=1)
    lead = _AgentStub(id=uuid4(), board_id=board_id, is_board_lead=True)
    actor = SimpleNamespace(actor_type="agent", user=None, agent=lead)
    payload = AgentCreate(name="Worker Agent", board_id=board_id)

    async def _fake_require_board(*_args: object, **_kwargs: object) -> _BoardStub:
        return board

    async def _fake_count_non_lead_agents_for_board(*, board_id: UUID) -> int:
        assert board_id == board.id
        return 1

    monkeypatch.setattr(service, "require_board", _fake_require_board)
    monkeypatch.setattr(
        service,
        "count_non_lead_agents_for_board",
        _fake_count_non_lead_agents_for_board,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_agent(payload=payload, actor=actor)  # type: ignore[arg-type]

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "excluding the lead" in str(exc_info.value.detail)
    assert "max_agents=1" in str(exc_info.value.detail)
