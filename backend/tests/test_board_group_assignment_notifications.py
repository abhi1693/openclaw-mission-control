# ruff: noqa: S101
"""Tests for board-group assignment notifications to board agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api import boards
from app.models.agents import Agent
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.schemas.boards import BoardUpdate
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError


@dataclass
class _FakeSession:
    added: list[object] = field(default_factory=list)
    commits: int = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


def _board(*, board_group_id: UUID | None) -> Board:
    return Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Platform",
        slug="platform",
        gateway_id=uuid4(),
        board_group_id=board_group_id,
    )


def _group(group_id: UUID, org_id: UUID) -> BoardGroup:
    return BoardGroup(
        id=group_id,
        organization_id=org_id,
        name="Execution Group",
        slug="execution-group",
    )


@pytest.mark.asyncio
async def test_update_board_notifies_agents_when_added_to_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board(board_group_id=None)
    session = _FakeSession()
    group_id = uuid4()
    group = _group(group_id, board.organization_id)
    payload = BoardUpdate(board_group_id=group_id)
    calls: dict[str, int] = {"notify": 0}

    async def _fake_apply_board_update(**kwargs: Any) -> Board:
        target: Board = kwargs["board"]
        target.board_group_id = group_id
        return target

    async def _fake_notify(**_kwargs: Any) -> None:
        calls["notify"] += 1

    async def _fake_get_by_id(*_args: Any, **_kwargs: Any) -> BoardGroup:
        return group

    monkeypatch.setattr(boards, "_apply_board_update", _fake_apply_board_update)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_addition", _fake_notify)
    monkeypatch.setattr(boards.crud, "get_by_id", _fake_get_by_id)

    updated = await boards.update_board(
        payload=payload,
        session=session,  # type: ignore[arg-type]
        board=board,
    )

    assert updated.board_group_id == group_id
    assert calls["notify"] == 1


@pytest.mark.asyncio
async def test_update_board_notifies_agents_when_removed_from_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    board = _board(board_group_id=group_id)
    session = _FakeSession()
    group = _group(group_id, board.organization_id)
    payload = BoardUpdate(board_group_id=None)
    calls: dict[str, int] = {"join": 0, "leave": 0}

    async def _fake_apply_board_update(**kwargs: Any) -> Board:
        target: Board = kwargs["board"]
        target.board_group_id = None
        return target

    async def _fake_join(**_kwargs: Any) -> None:
        calls["join"] += 1

    async def _fake_leave(**_kwargs: Any) -> None:
        calls["leave"] += 1

    async def _fake_get_by_id(*_args: Any, **_kwargs: Any) -> BoardGroup:
        return group

    monkeypatch.setattr(boards, "_apply_board_update", _fake_apply_board_update)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_addition", _fake_join)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_removal", _fake_leave)
    monkeypatch.setattr(boards.crud, "get_by_id", _fake_get_by_id)

    updated = await boards.update_board(
        payload=payload,
        session=session,  # type: ignore[arg-type]
        board=board,
    )

    assert updated.board_group_id is None
    assert calls["leave"] == 1
    assert calls["join"] == 0


@pytest.mark.asyncio
async def test_update_board_notifies_agents_when_moved_between_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_group_id = uuid4()
    new_group_id = uuid4()
    board = _board(board_group_id=old_group_id)
    session = _FakeSession()
    old_group = _group(old_group_id, board.organization_id)
    new_group = _group(new_group_id, board.organization_id)
    payload = BoardUpdate(board_group_id=new_group_id)
    calls: dict[str, int] = {"join": 0, "leave": 0}

    async def _fake_apply_board_update(**kwargs: Any) -> Board:
        target: Board = kwargs["board"]
        target.board_group_id = new_group_id
        return target

    async def _fake_join(**_kwargs: Any) -> None:
        calls["join"] += 1

    async def _fake_leave(**_kwargs: Any) -> None:
        calls["leave"] += 1

    async def _fake_get_by_id(_session: Any, _model: Any, obj_id: UUID) -> BoardGroup | None:
        if obj_id == old_group_id:
            return old_group
        if obj_id == new_group_id:
            return new_group
        return None

    monkeypatch.setattr(boards, "_apply_board_update", _fake_apply_board_update)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_addition", _fake_join)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_removal", _fake_leave)
    monkeypatch.setattr(boards.crud, "get_by_id", _fake_get_by_id)

    updated = await boards.update_board(
        payload=payload,
        session=session,  # type: ignore[arg-type]
        board=board,
    )

    assert updated.board_group_id == new_group_id
    assert calls["leave"] == 1
    assert calls["join"] == 1


@pytest.mark.asyncio
async def test_update_board_does_not_notify_when_group_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    board = _board(board_group_id=group_id)
    session = _FakeSession()
    payload = BoardUpdate(name="Platform X")
    calls: dict[str, int] = {"notify": 0}

    async def _fake_apply_board_update(**kwargs: Any) -> Board:
        target: Board = kwargs["board"]
        target.name = "Platform X"
        return target

    async def _fake_notify(**_kwargs: Any) -> None:
        calls["notify"] += 1

    monkeypatch.setattr(boards, "_apply_board_update", _fake_apply_board_update)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_addition", _fake_notify)
    monkeypatch.setattr(boards, "_notify_agents_on_board_group_removal", _fake_notify)

    updated = await boards.update_board(
        payload=payload,
        session=session,  # type: ignore[arg-type]
        board=board,
    )

    assert updated.name == "Platform X"
    assert calls["notify"] == 0


@pytest.mark.asyncio
async def test_notify_agents_on_board_group_addition_fanout_and_records_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    board = _board(board_group_id=group_id)
    peer_board = Board(
        id=uuid4(),
        organization_id=board.organization_id,
        name="Operations",
        slug="operations",
        gateway_id=board.gateway_id,
        board_group_id=group_id,
    )
    group = _group(group_id, board.organization_id)
    session = _FakeSession()
    sent: list[dict[str, Any]] = []

    agent_ok = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id or uuid4(),
        name="Lead",
        openclaw_session_id="agent:lead:session",
    )
    agent_skip = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id or uuid4(),
        name="Observer",
        openclaw_session_id=None,
    )
    agent_fail = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id or uuid4(),
        name="Worker",
        openclaw_session_id="agent:worker:session",
    )
    agent_peer = Agent(
        id=uuid4(),
        board_id=peer_board.id,
        gateway_id=peer_board.gateway_id or uuid4(),
        name="Partner",
        openclaw_session_id="agent:partner:session",
    )

    class _FakeBoardQuery:
        async def all(self, _session: object) -> list[Board]:
            return [board, peer_board]

    class _FakeBoardObjects:
        @staticmethod
        def filter_by(**_kwargs: Any) -> _FakeBoardQuery:
            return _FakeBoardQuery()

    class _FakeBoardModel:
        objects = _FakeBoardObjects()

    class _FakeAgentQuery:
        async def all(self, _session: object) -> list[Agent]:
            return [agent_ok, agent_skip, agent_fail, agent_peer]

    class _FakeAgentObjects:
        @staticmethod
        def by_field_in(*_args: Any, **_kwargs: Any) -> _FakeAgentQuery:
            return _FakeAgentQuery()

    class _FakeAgentModel:
        objects = _FakeAgentObjects()

    async def _fake_optional_gateway_config_for_board(
        self: boards.GatewayDispatchService,
        target_board: Board,
    ) -> GatewayClientConfig:
        _ = self
        return GatewayClientConfig(url=f"ws://gateway.example/ws/{target_board.id}", token=None)

    async def _fake_try_send_agent_message(
        self: boards.GatewayDispatchService,
        **kwargs: Any,
    ) -> OpenClawGatewayError | None:
        _ = self
        sent.append(kwargs)
        if kwargs["session_key"] == "agent:worker:session":
            return OpenClawGatewayError("gateway down")
        return None

    monkeypatch.setattr(boards, "Agent", _FakeAgentModel)
    monkeypatch.setattr(boards, "Board", _FakeBoardModel)
    monkeypatch.setattr(
        boards.GatewayDispatchService,
        "optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        boards.GatewayDispatchService,
        "try_send_agent_message",
        _fake_try_send_agent_message,
    )

    await boards._notify_agents_on_board_group_addition(
        session=session,  # type: ignore[arg-type]
        board=board,
        group=group,
    )

    assert len(sent) == 3
    assert {item["agent_name"] for item in sent} == {"Lead", "Worker", "Partner"}
    assert "BOARD GROUP UPDATED" in sent[0]["message"]
    assert "cross-board discussion" in sent[0]["message"].lower()
    assert "Joined Board: Platform" in sent[0]["message"]

    peer_message = next(item["message"] for item in sent if item["agent_name"] == "Partner")
    assert "Recipient Board: Operations" in peer_message

    event_types = [getattr(item, "event_type", "") for item in session.added]
    assert "board.group.join.notified" in event_types
    assert "board.group.join.notify_failed" in event_types
    assert session.commits == 1


@pytest.mark.asyncio
async def test_notify_agents_on_board_group_removal_fanout_and_records_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    board = _board(board_group_id=None)
    peer_board = Board(
        id=uuid4(),
        organization_id=board.organization_id,
        name="Operations",
        slug="operations",
        gateway_id=board.gateway_id,
        board_group_id=group_id,
    )
    group = _group(group_id, board.organization_id)
    session = _FakeSession()
    sent: list[dict[str, Any]] = []

    agent_board = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id or uuid4(),
        name="Lead",
        openclaw_session_id="agent:lead:session",
    )
    agent_peer = Agent(
        id=uuid4(),
        board_id=peer_board.id,
        gateway_id=peer_board.gateway_id or uuid4(),
        name="Partner",
        openclaw_session_id="agent:partner:session",
    )

    class _FakeBoardQuery:
        async def all(self, _session: object) -> list[Board]:
            return [peer_board]

    class _FakeBoardObjects:
        @staticmethod
        def filter_by(**_kwargs: Any) -> _FakeBoardQuery:
            return _FakeBoardQuery()

    class _FakeBoardModel:
        objects = _FakeBoardObjects()

    class _FakeAgentQuery:
        async def all(self, _session: object) -> list[Agent]:
            return [agent_board, agent_peer]

    class _FakeAgentObjects:
        @staticmethod
        def by_field_in(*_args: Any, **_kwargs: Any) -> _FakeAgentQuery:
            return _FakeAgentQuery()

    class _FakeAgentModel:
        objects = _FakeAgentObjects()

    async def _fake_optional_gateway_config_for_board(
        self: boards.GatewayDispatchService,
        target_board: Board,
    ) -> GatewayClientConfig:
        _ = self
        return GatewayClientConfig(url=f"ws://gateway.example/ws/{target_board.id}", token=None)

    async def _fake_try_send_agent_message(
        self: boards.GatewayDispatchService,
        **kwargs: Any,
    ) -> OpenClawGatewayError | None:
        _ = self
        sent.append(kwargs)
        return None

    monkeypatch.setattr(boards, "Agent", _FakeAgentModel)
    monkeypatch.setattr(boards, "Board", _FakeBoardModel)
    monkeypatch.setattr(
        boards.GatewayDispatchService,
        "optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        boards.GatewayDispatchService,
        "try_send_agent_message",
        _fake_try_send_agent_message,
    )

    await boards._notify_agents_on_board_group_removal(
        session=session,  # type: ignore[arg-type]
        board=board,
        group=group,
    )

    assert len(sent) == 2
    assert {item["agent_name"] for item in sent} == {"Lead", "Partner"}
    assert "Left Board: Platform" in sent[0]["message"]
    assert "Recipient Board: Platform" in next(
        item["message"] for item in sent if item["agent_name"] == "Lead"
    )
    assert "Recipient Board: Operations" in next(
        item["message"] for item in sent if item["agent_name"] == "Partner"
    )

    event_types = [getattr(item, "event_type", "") for item in session.added]
    assert "board.group.leave.notified" in event_types
    assert session.commits == 1
