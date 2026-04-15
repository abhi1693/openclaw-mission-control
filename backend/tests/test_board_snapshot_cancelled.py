# ruff: noqa: INP001

from __future__ import annotations

from uuid import uuid4

from app.models.tasks import Task
from app.services.board_snapshot import _task_to_card
from app.services.tags import TagState


def test_task_to_card_treats_cancelled_task_as_unblocked() -> None:
    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Cancelled task",
        status="cancelled",
    )
    dependency_id = uuid4()

    card = _task_to_card(
        task,
        agent_name_by_id={},
        counts_by_task_id={},
        deps_by_task_id={task.id: [dependency_id]},
        dependency_status_by_id_map={dependency_id: "inbox"},
        tag_state_by_task_id={task.id: TagState()},
    )

    assert card.status == "cancelled"
    assert card.blocked_by_task_ids == []
    assert card.is_blocked is False
