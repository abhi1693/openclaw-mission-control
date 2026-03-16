from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.api.tasks import _coerce_task_event_rows, _task_event_payload
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


def test_task_event_payload_includes_activity_for_comment_event() -> None:
    task = Task(board_id=uuid4(), title="Ship patch")
    event = ActivityEvent(
        event_type="task.comment",
        message="Looks good.",
        task_id=task.id,
        agent_id=uuid4(),
    )

    payload = _task_event_payload(
        event,
        task,
        deps_map={},
        dep_status={},
        tag_state_by_task_id={},
    )

    assert payload["type"] == "task.comment"
    assert payload["activity"] == {
        "id": str(event.id),
        "event_type": "task.comment",
        "message": "Looks good.",
        "agent_id": str(event.agent_id),
        "task_id": str(task.id),
        "created_at": event.created_at.isoformat(),
    }
    comment = payload["comment"]
    assert isinstance(comment, dict)
    assert comment["id"] == str(event.id)
    assert comment["task_id"] == str(task.id)
    assert comment["message"] == "Looks good."


def test_task_event_payload_includes_activity_for_non_comment_event() -> None:
    task = Task(board_id=uuid4(), title="Wire stream events", status="in_progress")
    event = ActivityEvent(
        event_type="task.updated",
        message="Task updated: Wire stream events.",
        task_id=task.id,
    )

    payload = _task_event_payload(
        event,
        task,
        deps_map={},
        dep_status={},
        tag_state_by_task_id={},
    )

    assert payload["type"] == "task.updated"
    assert payload["activity"] == {
        "id": str(event.id),
        "event_type": "task.updated",
        "message": "Task updated: Wire stream events.",
        "agent_id": None,
        "task_id": str(task.id),
        "created_at": event.created_at.isoformat(),
    }
    task_payload = payload["task"]
    assert isinstance(task_payload, dict)
    assert task_payload["id"] == str(task.id)
    assert task_payload["is_blocked"] is False
