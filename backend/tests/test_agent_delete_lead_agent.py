# ruff: noqa: S101
"""Unit tests for lead-agent delete behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

import app.services.openclaw.provisioning_db as agent_service
from app.models.board_webhooks import BoardWebhook
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig


@dataclass
class _FakeSession:
    committed: int = 0
    deleted: list[object] = field(default_factory=list)

    def add(self, _value: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def delete(self, value: object) -> None:
        self.deleted.append(value)


@dataclass
class _AgentStub:
    id: UUID
    name: str
    gateway_id: UUID
    board_id: UUID | None = None
    is_board_lead: bool = False


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID


@dataclass
class _GatewayStub:
    id: UUID
    url: str
    token: str | None
    workspace_root: str
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False


@pytest.mark.asyncio
async def test_delete_agent_as_lead_removes_board_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = agent_service.AgentLifecycleService(session)  # type: ignore[arg-type]

    gateway_id = uuid4()
    board = _BoardStub(id=uuid4(), gateway_id=gateway_id)
    lead = _AgentStub(
        id=uuid4(),
        name="Lead Agent",
        gateway_id=gateway_id,
        board_id=board.id,
        is_board_lead=True,
    )
    target = _AgentStub(
        id=uuid4(),
        name="Worker Agent",
        gateway_id=gateway_id,
        board_id=board.id,
        is_board_lead=False,
    )

    async def _fake_first_agent(_session: object) -> _AgentStub:
        return target

    monkeypatch.setattr(
        agent_service.Agent,
        "objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=_fake_first_agent)),
    )

    async def _fake_require_board(_board_id: object, **_kwargs: object) -> _BoardStub:
        return board

    async def _fake_require_gateway(
        _board: object,
    ) -> tuple[_GatewayStub, GatewayClientConfig]:
        gateway = _GatewayStub(
            id=gateway_id,
            url="ws://gateway.example/ws",
            token=None,
            workspace_root="/tmp/openclaw",
        )
        return gateway, GatewayClientConfig(url=gateway.url, token=None)

    async def _fake_delete_agent_lifecycle(
        _self,
        *,
        agent: object,
        gateway: object,
        delete_files: bool = True,
        delete_session: bool = True,
    ) -> str | None:
        _ = (_self, agent, gateway, delete_files, delete_session)
        return None

    update_models: list[type[object]] = []

    async def _fake_update_where(_session, model, *_args, **_kwargs) -> None:
        update_models.append(model)
        return None

    monkeypatch.setattr(service, "require_board", _fake_require_board)
    monkeypatch.setattr(service, "require_gateway", _fake_require_gateway)
    monkeypatch.setattr(
        agent_service.OpenClawGatewayProvisioner,
        "delete_agent_lifecycle",
        _fake_delete_agent_lifecycle,
    )
    monkeypatch.setattr(agent_service.crud, "update_where", _fake_update_where)
    monkeypatch.setattr(agent_service, "record_activity", lambda *_a, **_k: None)

    result = await service.delete_agent_as_lead(
        agent_id=str(target.id),
        actor_agent=lead,  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert session.deleted and session.deleted[0] == target
    assert BoardWebhook in update_models


@pytest.mark.asyncio
async def test_delete_agent_as_lead_rejects_gateway_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = agent_service.AgentLifecycleService(session)  # type: ignore[arg-type]

    gateway_id = uuid4()
    board_id = uuid4()
    lead = _AgentStub(
        id=uuid4(),
        name="Lead Agent",
        gateway_id=gateway_id,
        board_id=board_id,
        is_board_lead=True,
    )
    target = _AgentStub(
        id=uuid4(),
        name="Gateway Main",
        gateway_id=gateway_id,
        board_id=None,
        is_board_lead=False,
    )

    async def _fake_first_agent(_session: object) -> _AgentStub:
        return target

    monkeypatch.setattr(
        agent_service.Agent,
        "objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=_fake_first_agent)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_agent_as_lead(
            agent_id=str(target.id),
            actor_agent=lead,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "gateway main" in str(exc_info.value.detail).lower()
