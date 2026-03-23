# ruff: noqa: S101
"""Unit tests for board-lead agent recovery coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

import app.services.openclaw.coordination_service as coordination_lifecycle
from app.core.time import utcnow


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
    gateway_id: UUID
    board_id: UUID | None = None
    openclaw_session_id: str | None = None
    last_wake_sent_at: object | None = None


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID | None
    name: str


@pytest.mark.asyncio
async def test_gateway_coordination_recover_runs_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = coordination_lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Supervisor", gateway_id=board.gateway_id, board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="DevOps",
        gateway_id=board.gateway_id,
        board_id=board.id,
        openclaw_session_id="agent:devops:main",
    )
    captured: dict[str, object] = {}

    async def _fake_board_agent_or_404(
        self: coordination_lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    async def _fake_gateway_by_id(_session: object) -> SimpleNamespace:
        _ = _session
        return SimpleNamespace(id=board.gateway_id, url="ws://gateway.example/ws")

    class _GatewayQuery:
        async def first(self, _session: object) -> object:
            return await _fake_gateway_by_id(_session)

    class _GatewayObjects:
        @staticmethod
        def by_id(_gateway_id: UUID) -> _GatewayQuery:
            assert _gateway_id == board.gateway_id
            return _GatewayQuery()

    class _OrchestratorStub:
        def __init__(self, _session: object) -> None:
            captured["orchestrator_session"] = _session

        async def run_lifecycle(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return target

    monkeypatch.setattr(
        coordination_lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    async def _fake_existing_auth_token(**_kwargs: object) -> str:
        return "existing-token"

    monkeypatch.setattr(
        coordination_lifecycle,
        "_get_existing_auth_token",
        _fake_existing_auth_token,
    )
    monkeypatch.setattr(
        coordination_lifecycle,
        "_control_plane_for_gateway",
        lambda _gateway: object(),
    )
    monkeypatch.setattr(coordination_lifecycle, "Gateway", SimpleNamespace(objects=_GatewayObjects()))
    monkeypatch.setattr(coordination_lifecycle, "AgentLifecycleOrchestrator", _OrchestratorStub)

    await service.recover_board_agent(
        board=board,  # type: ignore[arg-type]
        actor_agent=actor,  # type: ignore[arg-type]
        target_agent_id=str(target.id),
    )

    assert captured["orchestrator_session"] is session
    assert captured["gateway"].id == board.gateway_id
    assert captured["agent_id"] == target.id
    assert captured["board"] == board
    assert captured["action"] == "update"
    assert captured["auth_token"] == "existing-token"
    assert captured["force_bootstrap"] is False
    assert captured["reset_session"] is True
    assert captured["wake"] is True
    assert captured["deliver_wakeup"] is True
    assert captured["wakeup_verb"] == "updated"
    assert session.committed == 1


@pytest.mark.asyncio
async def test_gateway_coordination_recover_rejects_recent_repeat_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = coordination_lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Supervisor", gateway_id=board.gateway_id, board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="DevOps",
        gateway_id=board.gateway_id,
        board_id=board.id,
        last_wake_sent_at=utcnow() - timedelta(seconds=30),
    )

    async def _fake_board_agent_or_404(
        self: coordination_lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    monkeypatch.setattr(
        coordination_lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.recover_board_agent(
            board=board,  # type: ignore[arg-type]
            actor_agent=actor,  # type: ignore[arg-type]
            target_agent_id=str(target.id),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "recently recovered" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_gateway_coordination_recover_requires_existing_auth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = coordination_lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Supervisor", gateway_id=board.gateway_id, board_id=board.id)
    target = _AgentStub(id=uuid4(), name="DevOps", gateway_id=board.gateway_id, board_id=board.id)

    async def _fake_board_agent_or_404(
        self: coordination_lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    class _GatewayQuery:
        async def first(self, _session: object) -> object:
            return SimpleNamespace(id=board.gateway_id, url="ws://gateway.example/ws")

    class _GatewayObjects:
        @staticmethod
        def by_id(_gateway_id: UUID) -> _GatewayQuery:
            return _GatewayQuery()

    monkeypatch.setattr(
        coordination_lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    monkeypatch.setattr(coordination_lifecycle, "Gateway", SimpleNamespace(objects=_GatewayObjects()))
    async def _fake_missing_auth_token(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(coordination_lifecycle, "_get_existing_auth_token", _fake_missing_auth_token)
    monkeypatch.setattr(
        coordination_lifecycle,
        "_control_plane_for_gateway",
        lambda _gateway: object(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.recover_board_agent(
            board=board,  # type: ignore[arg-type]
            actor_agent=actor,  # type: ignore[arg-type]
            target_agent_id=str(target.id),
        )

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "auth token unavailable" in str(exc_info.value.detail)
