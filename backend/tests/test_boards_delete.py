# ruff: noqa: INP001, S101
"""Regression tests for board deletion cleanup behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.services.board_lifecycle as board_lifecycle
from app.api import boards
from app.models.boards import Board
from app.services.openclaw.gateway_rpc import OpenClawGatewayError

_NO_EXEC_RESULTS_ERROR = "No more exec_results left for session.exec"


@dataclass
class _FakeSession:
    exec_results: list[object]
    executed: list[object] = field(default_factory=list)
    deleted: list[object] = field(default_factory=list)
    committed: int = 0

    async def exec(self, statement: object) -> object | None:
        is_dml = statement.__class__.__name__ in {"Delete", "Update", "Insert"}
        if is_dml:
            self.executed.append(statement)
            return None
        if not self.exec_results:
            raise AssertionError(_NO_EXEC_RESULTS_ERROR)
        return self.exec_results.pop(0)

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def delete(self, value: object) -> None:
        self.deleted.append(value)

    async def commit(self) -> None:
        self.committed += 1


@pytest.mark.asyncio
async def test_delete_board_cleans_org_board_access_rows() -> None:
    """Deleting a board should clear org-board access rows before commit."""
    session: Any = _FakeSession(exec_results=[[], []])
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Demo Board",
        slug="demo-board",
        gateway_id=None,
    )

    await boards.delete_board(
        session=session,
        board=board,
    )

    deleted_table_names = [statement.table.name for statement in session.executed]
    assert "organization_board_access" in deleted_table_names
    assert "organization_invite_board_access" in deleted_table_names
    assert board in session.deleted
    assert session.committed == 1


@pytest.mark.asyncio
async def test_delete_board_cleans_tag_assignments_before_tasks() -> None:
    """Deleting a board should remove task-tag links before deleting tasks."""
    session: Any = _FakeSession(exec_results=[[], [uuid4()]])
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Demo Board",
        slug="demo-board",
        gateway_id=None,
    )

    await boards.delete_board(
        session=session,
        board=board,
    )

    deleted_table_names = [statement.table.name for statement in session.executed]
    assert "tag_assignments" in deleted_table_names
    assert deleted_table_names.index("tag_assignments") < deleted_table_names.index("tasks")


@pytest.mark.asyncio
async def test_delete_board_ignores_missing_gateway_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting a board should continue when gateway reports agent not found."""
    session: Any = _FakeSession(exec_results=[[]])
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Demo Board",
        slug="demo-board",
        gateway_id=uuid4(),
    )
    agent = SimpleNamespace(id=uuid4(), board_id=board.id)
    gateway = SimpleNamespace(url="ws://gateway.example/ws", token=None, workspace_root="/tmp")
    called = {"delete_agent_lifecycle": 0}

    async def _fake_all(_session: object) -> list[object]:
        return [agent]

    async def _fake_require_gateway_for_board(
        _session: object,
        _board: object,
        *,
        require_workspace_root: bool,
    ) -> object:
        _ = require_workspace_root
        return gateway

    async def _fake_delete_agent_lifecycle(
        _self: object,
        *,
        agent: object,
        gateway: object,
        delete_files: bool = True,
        delete_session: bool = True,
    ) -> str | None:
        _ = (agent, gateway, delete_files, delete_session)
        called["delete_agent_lifecycle"] += 1
        raise OpenClawGatewayError('agent "mc-worker" not found')

    monkeypatch.setattr(
        board_lifecycle.Agent,
        "objects",
        SimpleNamespace(filter_by=lambda **_kwargs: SimpleNamespace(all=_fake_all)),
    )
    monkeypatch.setattr(
        board_lifecycle,
        "require_gateway_for_board",
        _fake_require_gateway_for_board,
    )
    monkeypatch.setattr(board_lifecycle, "gateway_client_config", lambda _gateway: None)
    monkeypatch.setattr(
        board_lifecycle.OpenClawGatewayProvisioner,
        "delete_agent_lifecycle",
        _fake_delete_agent_lifecycle,
    )

    await boards.delete_board(
        session=session,
        board=board,
    )

    assert called["delete_agent_lifecycle"] == 1
    assert board in session.deleted
    assert session.committed == 1
