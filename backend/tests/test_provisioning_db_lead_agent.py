# ruff: noqa: S101
"""Unit tests for board-lead provisioning name behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.services.openclaw.provisioning_db as provisioning_db
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.provisioning_db import (
    LeadAgentOptions,
    LeadAgentRequest,
    OpenClawProvisioningService,
)


class _ExecResult:
    def __init__(self, value: Agent | None) -> None:
        self._value = value

    def first(self) -> Agent | None:
        return self._value


@dataclass
class _FakeSession:
    existing: Agent | None
    commits: int = 0
    added: list[object] = field(default_factory=list)
    refreshed: list[object] = field(default_factory=list)

    async def exec(self, _statement: object) -> _ExecResult:
        return _ExecResult(self.existing)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


def _board() -> Board:
    organization_id = uuid4()
    gateway_id = uuid4()
    return Board(
        id=uuid4(),
        organization_id=organization_id,
        gateway_id=gateway_id,
        name="Roadmap",
        slug="roadmap",
    )


def _gateway(*, organization_id: UUID) -> Gateway:
    return Gateway(
        id=uuid4(),
        organization_id=organization_id,
        name="Gateway",
        url="ws://gateway.example/ws",
        workspace_root="/tmp/openclaw",
    )


def _request(
    *,
    board: Board,
    gateway: Gateway,
    options: LeadAgentOptions | None = None,
) -> LeadAgentRequest:
    return LeadAgentRequest(
        board=board,
        gateway=gateway,
        config=GatewayClientConfig(url=gateway.url, token=None),
        user=None,
        options=options or LeadAgentOptions(),
    )


@pytest.mark.asyncio
async def test_ensure_board_lead_agent_preserves_existing_custom_name_without_override() -> None:
    board = _board()
    gateway = _gateway(organization_id=board.organization_id)
    existing = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="Roadmap Captain",
        is_board_lead=True,
        openclaw_session_id=OpenClawProvisioningService.lead_session_key(board),
    )
    session = _FakeSession(existing=existing)
    service = OpenClawProvisioningService(session)  # type: ignore[arg-type]

    lead, created = await service.ensure_board_lead_agent(
        request=_request(board=board, gateway=gateway),
    )

    assert created is False
    assert lead.name == "Roadmap Captain"
    assert session.commits == 0


@pytest.mark.asyncio
async def test_ensure_board_lead_agent_defaults_new_lead_name_when_none_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board()
    gateway = _gateway(organization_id=board.organization_id)
    session = _FakeSession(existing=None)
    service = OpenClawProvisioningService(session)  # type: ignore[arg-type]
    captured: dict[str, Any] = {}

    monkeypatch.setattr(provisioning_db, "mint_agent_token", lambda _agent: "raw-token")

    class _FakeOrchestrator:
        def __init__(self, _session: object) -> None:
            captured["session"] = _session

        async def run_lifecycle(self, **kwargs: Any) -> Agent:
            captured["kwargs"] = kwargs
            agent = next(item for item in session.added if isinstance(item, Agent))
            return agent

    monkeypatch.setattr(provisioning_db, "AgentLifecycleOrchestrator", _FakeOrchestrator)

    lead, created = await service.ensure_board_lead_agent(
        request=_request(board=board, gateway=gateway),
    )

    assert created is True
    assert lead.name == "Lead Agent"
    assert lead.is_board_lead is True
    assert lead.openclaw_session_id == OpenClawProvisioningService.lead_session_key(board)
    assert session.commits == 1
    assert captured["session"] is session
    assert captured["kwargs"]["auth_token"] == "raw-token"
