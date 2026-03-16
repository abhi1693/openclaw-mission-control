# ruff: noqa: S101
"""Unit tests for agent deletion behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.services.openclaw.provisioning_db as agent_service
from app.models.approvals import Approval


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
    openclaw_session_id: str | None = None


@dataclass
class _GatewayStub:
    id: UUID
    url: str
    token: str | None
    workspace_root: str
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False


@pytest.mark.asyncio
async def test_delete_gateway_main_agent_does_not_require_board_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = agent_service.AgentLifecycleService(session)  # type: ignore[arg-type]

    gateway_id = uuid4()
    agent = _AgentStub(
        id=uuid4(),
        name="Primary Gateway Agent",
        gateway_id=gateway_id,
        board_id=None,
        openclaw_session_id="agent:gateway-x:main",
    )
    gateway = _GatewayStub(
        id=gateway_id,
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    ctx = SimpleNamespace(
        organization=SimpleNamespace(id=uuid4()), member=SimpleNamespace(id=uuid4())
    )

    async def _fake_first_agent(_session: object) -> _AgentStub:
        return agent

    async def _fake_first_gateway(_session: object) -> _GatewayStub:
        return gateway

    monkeypatch.setattr(
        agent_service.Agent,
        "objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=_fake_first_agent)),
    )
    monkeypatch.setattr(
        agent_service.Gateway,
        "objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=_fake_first_gateway)),
    )

    async def _no_access_check(*_args, **_kwargs) -> None:
        return None

    async def _should_not_be_called(*_args, **_kwargs):
        raise AssertionError("require_board/require_gateway should not be called for main agents")

    called: dict[str, int] = {"delete_lifecycle": 0}

    async def _fake_delete_agent_lifecycle(
        _self,
        *,
        agent: object,
        gateway: object,
        delete_files: bool = True,
        delete_session: bool = True,
    ) -> str | None:
        _ = (_self, agent, gateway, delete_files, delete_session)
        called["delete_lifecycle"] += 1
        return "/tmp/openclaw/workspace-gateway-x"

    updated_models: list[type[object]] = []

    async def _fake_update_where(*_args, **_kwargs) -> None:
        if len(_args) >= 2 and isinstance(_args[1], type):
            updated_models.append(_args[1])
        return None

    monkeypatch.setattr(service, "require_agent_access", _no_access_check)
    monkeypatch.setattr(service, "require_board", _should_not_be_called)
    monkeypatch.setattr(service, "require_gateway", _should_not_be_called)
    monkeypatch.setattr(
        agent_service.OpenClawGatewayProvisioner,
        "delete_agent_lifecycle",
        _fake_delete_agent_lifecycle,
    )
    monkeypatch.setattr(agent_service.crud, "update_where", _fake_update_where)
    monkeypatch.setattr(agent_service, "record_activity", lambda *_a, **_k: None)

    result = await service.delete_agent(agent_id=str(agent.id), ctx=ctx)  # type: ignore[arg-type]

    assert result.ok is True
    assert called["delete_lifecycle"] == 1
    assert Approval in updated_models
    assert session.deleted and session.deleted[0] == agent
