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


def test_task_to_card_treats_operator_decision_task_as_blocked_without_dependencies() -> None:
    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Await operator decision",
        status="in_progress",
        operator_decision_required=True,
        operator_decision_summary="Awaiting pricing decision.",
    )

    card = _task_to_card(
        task,
        agent_name_by_id={},
        counts_by_task_id={},
        deps_by_task_id={task.id: []},
        dependency_status_by_id_map={},
        tag_state_by_task_id={task.id: TagState()},
    )

    assert card.operator_decision_required is True
    assert card.operator_decision_summary == "Awaiting pricing decision."
    assert card.blocked_by_task_ids == []
    assert card.is_blocked is True


def test_task_to_card_treats_open_blocker_as_blocked_without_dependencies() -> None:
    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Runtime parked task",
        status="in_progress",
    )

    card = _task_to_card(
        task,
        agent_name_by_id={},
        counts_by_task_id={},
        deps_by_task_id={task.id: []},
        dependency_status_by_id_map={},
        tag_state_by_task_id={task.id: TagState()},
        tasks_with_open_blocker={task.id},
        open_blocker_reason_codes_by_task_id={
            task.id: ["acp_runtime_unavailable"],
        },
    )

    assert card.blocked_by_task_ids == []
    assert card.open_blocker_reason_codes == ["acp_runtime_unavailable"]
    assert card.is_blocked is True


def test_task_to_card_treats_pending_operator_decision_as_blocked_without_legacy_flag() -> None:
    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Operator decision parked task",
        status="rework",
    )

    card = _task_to_card(
        task,
        agent_name_by_id={},
        counts_by_task_id={},
        deps_by_task_id={task.id: []},
        dependency_status_by_id_map={},
        tag_state_by_task_id={task.id: TagState()},
        tasks_with_pending_operator_decision={task.id},
        pending_operator_decision_reason_codes_by_task_id={
            task.id: ["operator_artifact_decision"],
        },
    )

    assert card.operator_decision_required is False
    assert card.pending_operator_decision_reason_codes == [
        "operator_artifact_decision",
    ]
    assert card.blocked_by_task_ids == []
    assert card.is_blocked is True
