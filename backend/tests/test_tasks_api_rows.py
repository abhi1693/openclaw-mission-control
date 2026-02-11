from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.api.tasks import _coerce_task_event_rows
from app.models.activity_events import ActivityEvent
from app.models.tasks import Task


@dataclass
class _FakeSqlRow:
    first: object
    second: object

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return self.first
        if index == 1:
            return self.second
        raise IndexError(index)


def _make_event() -> ActivityEvent:
    return ActivityEvent(event_type="task.updated")


def _make_task() -> Task:
    return Task(board_id=uuid4(), title="T")


def test_coerce_task_event_rows_accepts_plain_tuple():
    event = _make_event()
    task = _make_task()
    rows = _coerce_task_event_rows([(event, task)])
    assert rows == [(event, task)]


def test_coerce_task_event_rows_accepts_row_like_values():
    event = _make_event()
    task = _make_task()
    rows = _coerce_task_event_rows([_FakeSqlRow(event, task)])
    assert rows == [(event, task)]


def test_coerce_task_event_rows_rejects_invalid_values():
    with pytest.raises(TypeError, match="Expected \\(ActivityEvent, Task \\| None\\) rows"):
        _coerce_task_event_rows([("bad", "row")])
