# ruff: noqa: S101
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

import app.services.openclaw.provisioning_db as agent_service
from app.schemas.agents import AgentCreate


@dataclass
class _FakeExecResult:
    value: object | None

    def first(self) -> object | None:
        return self.value


@dataclass
class _FakeSession:
    exec_result: object | None = None

    async def exec(self, *_args: object, **_kwargs: object) -> _FakeExecResult:
        return _FakeExecResult(self.exec_result)


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID


@dataclass
class _GatewayStub:
    id: UUID


@dataclass
class _AgentStub:
    id: UUID
    name: str


@pytest.mark.asyncio
async def test_create_agent_sets_lead_session_key(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(exec_result=None)
    service = agent_service.AgentLifecycleService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4())
    gateway = _GatewayStub(id=board.gateway_id)
    actor = SimpleNamespace(actor_type="user", user=None)
    payload = AgentCreate(name="Lead", board_id=board.id, is_board_lead=True)
    captured: dict[str, object] = {}

    async def _fake_coerce(payload, actor):
        return payload

    async def _fake_require_board(*_args, **_kwargs):
        return board

    async def _fake_require_gateway(*_args, **_kwargs):
        return gateway, None

    async def _fake_enforce(*_args, **_kwargs):
        return None

    async def _fake_ensure_unique_agent_name(*_args, **_kwargs):
        return None

    async def _fake_persist_new_agent(*, data):
        captured["data"] = data
        return _AgentStub(id=uuid4(), name=data.get("name") or ""), "token"

    async def _fake_provision_new_agent(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "coerce_agent_create_payload", _fake_coerce)
    monkeypatch.setattr(service, "require_board", _fake_require_board)
    monkeypatch.setattr(service, "require_gateway", _fake_require_gateway)
    monkeypatch.setattr(service, "enforce_board_spawn_limit_for_lead", _fake_enforce)
    monkeypatch.setattr(service, "ensure_unique_agent_name", _fake_ensure_unique_agent_name)
    monkeypatch.setattr(service, "persist_new_agent", _fake_persist_new_agent)
    monkeypatch.setattr(service, "provision_new_agent", _fake_provision_new_agent)

    await service.create_agent(payload=payload, actor=actor)  # type: ignore[arg-type]

    expected_session_key = service.lead_session_key(board)
    assert captured["data"]["openclaw_session_id"] == expected_session_key


@pytest.mark.asyncio
async def test_create_agent_rejects_duplicate_board_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_lead = _AgentStub(id=uuid4(), name="Existing Lead")
    session = _FakeSession(exec_result=existing_lead)
    service = agent_service.AgentLifecycleService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4())
    gateway = _GatewayStub(id=board.gateway_id)
    actor = SimpleNamespace(actor_type="user", user=None)
    payload = AgentCreate(name="Lead", board_id=board.id, is_board_lead=True)

    async def _fake_coerce(payload, actor):
        return payload

    async def _fake_require_board(*_args, **_kwargs):
        return board

    async def _fake_require_gateway(*_args, **_kwargs):
        return gateway, None

    async def _fake_enforce(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "coerce_agent_create_payload", _fake_coerce)
    monkeypatch.setattr(service, "require_board", _fake_require_board)
    monkeypatch.setattr(service, "require_gateway", _fake_require_gateway)
    monkeypatch.setattr(service, "enforce_board_spawn_limit_for_lead", _fake_enforce)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_agent(payload=payload, actor=actor)  # type: ignore[arg-type]

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "already has a lead agent" in str(exc_info.value.detail)
