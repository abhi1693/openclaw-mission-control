from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.api import metrics as metrics_api
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.tasks import Task


class _ExecResult:
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, int]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        self._rows = rows

    async def exec(self, _statement: object) -> _ExecResult:
        return _ExecResult(self._rows)


class _ExecOneResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def one(self) -> int:
        return self._value


class _ExecAllResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _SequentialSession:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self._index = 0

    async def exec(self, _statement: object) -> object:
        response = self._responses[self._index]
        self._index += 1
        return response


@pytest.mark.asyncio
async def test_task_status_counts_returns_zeroes_for_empty_board_scope() -> None:
    counts = await metrics_api._task_status_counts(_FakeSession([]), [])

    assert counts == {
        "inbox": 0,
        "in_progress": 0,
        "review": 0,
        "done": 0,
    }


@pytest.mark.asyncio
async def test_task_status_counts_maps_known_statuses() -> None:
    session = _FakeSession(
        [
            ("inbox", 4),
            ("in_progress", 3),
            ("review", 2),
            ("done", 7),
            ("blocked", 99),
        ],
    )

    counts = await metrics_api._task_status_counts(session, [uuid4()])

    assert counts == {
        "inbox": 4,
        "in_progress": 3,
        "review": 2,
        "done": 7,
    }


@pytest.mark.asyncio
async def test_pending_approvals_snapshot_returns_empty_for_empty_scope() -> None:
    snapshot = await metrics_api._pending_approvals_snapshot(_SequentialSession([]), [])

    assert snapshot.total == 0
    assert snapshot.items == []


@pytest.mark.asyncio
async def test_pending_approvals_snapshot_maps_rows() -> None:
    approval_id = uuid4()
    board_id = uuid4()
    organization_id = uuid4()
    task_id = uuid4()
    created_at = datetime(2026, 3, 4, 12, 0, 0)
    approval = Approval(
        id=approval_id,
        board_id=board_id,
        task_id=task_id,
        action_type="approve_task",
        confidence=87.0,
        created_at=created_at,
        status="pending",
    )
    board = Board(
        id=board_id,
        organization_id=organization_id,
        name="Operations Board",
        slug="operations-board",
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Validate rollout checklist",
    )
    rows: list[tuple[object, ...]] = [
        (
            approval,
            board,
            task,
        )
    ]
    session = _SequentialSession(
        [
            _ExecOneResult(3),
            _ExecAllResult(rows),
        ]
    )

    snapshot = await metrics_api._pending_approvals_snapshot(session, [board_id], limit=10)

    assert snapshot.total == 3
    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.approval_id == approval_id
    assert item.board_id == board_id
    assert item.board_name == "Operations Board"
    assert item.action_type == "approve_task"
    assert item.confidence == 87.0
    assert item.created_at == created_at
    assert item.task_title == "Validate rollout checklist"
