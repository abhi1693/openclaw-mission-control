from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.api.activity import _coerce_task_comment_rows
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task


@dataclass
class _FakeSqlRow4:
    first: object
    second: object
    third: object
    fourth: object

    def __len__(self) -> int:
        return 4

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return self.first
        if index == 1:
            return self.second
        if index == 2:
            return self.third
        if index == 3:
            return self.fourth
        raise IndexError(index)


def _make_event() -> ActivityEvent:
    return ActivityEvent(event_type="task.comment", message="hello")


def _make_board() -> Board:
    return Board(
        organization_id=uuid4(),
        name="B",
        slug="b",
    )


def _make_task(board_id) -> Task:
    return Task(board_id=board_id, title="T")


def _make_agent(board_id) -> Agent:
    return Agent(
        board_id=board_id,
        gateway_id=uuid4(),
        name="A",
    )


def test_coerce_task_comment_rows_accepts_plain_tuple():
    board = _make_board()
    task = _make_task(board.id)
    event = _make_event()
    agent = _make_agent(board.id)

    rows = _coerce_task_comment_rows([(event, task, board, agent)])
    assert rows == [(event, task, board, agent)]


def test_coerce_task_comment_rows_accepts_row_like_values():
    board = _make_board()
    task = _make_task(board.id)
    event = _make_event()
    row = _FakeSqlRow4(event, task, board, None)

    rows = _coerce_task_comment_rows([row])
    assert rows == [(event, task, board, None)]


def test_coerce_task_comment_rows_rejects_invalid_values():
    board = _make_board()
    task = _make_task(board.id)

    with pytest.raises(
        TypeError,
        match="Expected \\(ActivityEvent, Task, Board, Agent \\| None\\) rows",
    ):
        _coerce_task_comment_rows([(uuid4(), task, board, None)])
