# ruff: noqa: S101
"""Unit tests for lifecycle coordination and onboarding messaging services."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError
from app.services.openclaw import services as lifecycle


@dataclass
class _FakeSession:
    committed: int = 0
    added: list[object] = field(default_factory=list)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1


@dataclass
class _AgentStub:
    id: UUID
    name: str
    openclaw_session_id: str | None = None
    board_id: UUID | None = None


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID | None
    name: str


@pytest.mark.asyncio
async def test_gateway_coordination_nudge_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Lead Agent", board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="Worker Agent",
        openclaw_session_id="agent:worker:main",
        board_id=board.id,
    )
    captured: list[dict[str, Any]] = []

    async def _fake_board_agent_or_404(
        self: lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    async def _fake_require_gateway_config_for_board(
        _session: object,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_gateway_agent_message(**kwargs: Any) -> dict[str, bool]:
        captured.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    monkeypatch.setattr(
        lifecycle,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        lifecycle,
        "send_gateway_agent_message",
        _fake_send_gateway_agent_message,
    )

    await service.nudge_board_agent(
        board=board,  # type: ignore[arg-type]
        actor_agent=actor,  # type: ignore[arg-type]
        target_agent_id=str(target.id),
        message="Please run BOOT.md",
        correlation_id="nudge-corr-id",
    )

    assert len(captured) == 1
    assert captured[0]["session_key"] == "agent:worker:main"
    assert captured[0]["agent_name"] == "Worker Agent"
    assert captured[0]["deliver"] is True
    assert session.committed == 1


@pytest.mark.asyncio
async def test_gateway_coordination_nudge_maps_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Lead Agent", board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="Worker Agent",
        openclaw_session_id="agent:worker:main",
        board_id=board.id,
    )

    async def _fake_board_agent_or_404(
        self: lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    async def _fake_require_gateway_config_for_board(
        _session: object,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_gateway_agent_message(**_kwargs: Any) -> None:
        raise OpenClawGatewayError("dial tcp: connection refused")

    monkeypatch.setattr(
        lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    monkeypatch.setattr(
        lifecycle,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        lifecycle,
        "send_gateway_agent_message",
        _fake_send_gateway_agent_message,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.nudge_board_agent(
            board=board,  # type: ignore[arg-type]
            actor_agent=actor,  # type: ignore[arg-type]
            target_agent_id=str(target.id),
            message="Please run BOOT.md",
            correlation_id="nudge-corr-id",
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Gateway nudge failed:" in str(exc_info.value.detail)
    assert session.committed == 1


@pytest.mark.asyncio
async def test_board_onboarding_dispatch_start_returns_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = lifecycle.BoardOnboardingMessagingService(session)  # type: ignore[arg-type]
    gateway_id = uuid4()
    board = _BoardStub(id=uuid4(), gateway_id=gateway_id, name="Roadmap")
    captured: list[dict[str, Any]] = []

    async def _fake_require_gateway_config_for_board(
        _session: object,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        gateway = SimpleNamespace(id=gateway_id, url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_gateway_agent_message(**kwargs: Any) -> dict[str, bool]:
        captured.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        lifecycle,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        lifecycle,
        "send_gateway_agent_message",
        _fake_send_gateway_agent_message,
    )

    session_key = await service.dispatch_start_prompt(
        board=board,  # type: ignore[arg-type]
        prompt="BOARD ONBOARDING REQUEST",
        correlation_id="onboarding-corr-id",
    )

    assert session_key == lifecycle.GatewayAgentIdentity.session_key_for_id(gateway_id)
    assert len(captured) == 1
    assert captured[0]["agent_name"] == "Gateway Agent"
    assert captured[0]["deliver"] is False


@pytest.mark.asyncio
async def test_board_onboarding_dispatch_answer_maps_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = lifecycle.BoardOnboardingMessagingService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    onboarding = SimpleNamespace(id=uuid4(), session_key="agent:gateway-main:main")

    async def _fake_require_gateway_config_for_board(
        _session: object,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_gateway_agent_message(**_kwargs: Any) -> None:
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(
        lifecycle,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        lifecycle,
        "send_gateway_agent_message",
        _fake_send_gateway_agent_message,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.dispatch_answer(
            board=board,  # type: ignore[arg-type]
            onboarding=onboarding,
            answer_text="I prefer concise updates.",
            correlation_id="onboarding-answer-corr-id",
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Gateway onboarding answer dispatch failed:" in str(exc_info.value.detail)
