from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.api.activity import _build_activity_route, _coerce_activity_rows, _coerce_task_comment_rows
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


@dataclass
class _FakeSqlRow3:
    first: object
    second: object
    third: object

    def __len__(self) -> int:
        return 3

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return self.first
        if index == 1:
            return self.second
        if index == 2:
            return self.third
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


def test_coerce_activity_rows_accepts_plain_tuple():
    board_id = uuid4()
    event = _make_event()

    rows = _coerce_activity_rows([(event, board_id, None)])
    assert rows == [(event, board_id, None)]


def test_coerce_activity_rows_accepts_row_like_values():
    board_id = uuid4()
    event = _make_event()
    row = _FakeSqlRow3(event, board_id, None)

    rows = _coerce_activity_rows([row])
    assert rows == [(event, board_id, None)]


def test_coerce_activity_rows_rejects_invalid_values():
    event = _make_event()
    with pytest.raises(
        TypeError,
        match="Expected \\(ActivityEvent, event_board_id, task_board_id\\) rows",
    ):
        _coerce_activity_rows([(event, "bad", None)])


def test_build_activity_route_board_comment():
    board_id = uuid4()
    task_id = uuid4()
    event = ActivityEvent(
        event_type="task.comment",
        task_id=task_id,
        message="hello",
    )
    route_name, route_params = _build_activity_route(event=event, board_id=board_id)
    assert route_name == "board"
    assert route_params == {
        "boardId": str(board_id),
        "taskId": str(task_id),
        "commentId": str(event.id),
    }


def test_build_activity_route_board_approvals():
    board_id = uuid4()
    event = ActivityEvent(
        event_type="approval.lead_notified",
        message="hello",
    )
    route_name, route_params = _build_activity_route(event=event, board_id=board_id)
    assert route_name == "board.approvals"
    assert route_params == {"boardId": str(board_id)}


def test_build_activity_route_global_fallback():
    event = ActivityEvent(
        event_type="gateway.main.lead_broadcast.sent",
        message="hello",
    )
    route_name, route_params = _build_activity_route(event=event, board_id=None)
    assert route_name == "activity"
    assert route_params["eventId"] == str(event.id)
    assert route_params["eventType"] == event.event_type
    assert route_params["createdAt"] == event.created_at.isoformat()
