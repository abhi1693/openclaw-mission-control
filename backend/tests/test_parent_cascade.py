# ruff: noqa: INP001
"""Phase V parent-child cascade: orphan detection + cancel_orphan_child action."""

from __future__ import annotations

from uuid import uuid4

from app.models.tasks import Task
from app.services.lead_next_action import select_lead_next_action


def _task(
    *,
    status: str = "inbox",
    title: str = "T",
    assigned: bool = False,
    parent_task_id=None,
) -> Task:
    return Task(
        id=uuid4(),
        board_id=uuid4(),
        title=title,
        status=status,
        assigned_agent_id=uuid4() if assigned else None,
        parent_task_id=parent_task_id,
    )


def test_orphan_child_action_returned_when_parent_terminal_and_child_active() -> None:
    parent = _task(status="done", title="Parent — shipped")
    child = _task(status="rework", title="Obsolete child", assigned=True)

    action = select_lead_next_action(
        tasks=[parent, child],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={child.id: parent.id},
    )

    assert action.action_required is True
    assert action.action == "cancel_orphan_child"
    assert action.reason_code == "non_terminal_child_of_terminal_parent"
    assert action.task_id == child.id
    assert action.details["parent_task_id"] == str(parent.id)
    assert action.details["orphan_count"] == 1


def test_orphan_action_overrides_route_inbox() -> None:
    """If both an unassigned inbox task AND an orphan child exist, drain the
    orphan first — cleanup of obsolete decomposition wins over allocating
    fresh inbox attention."""
    parent = _task(status="cancelled", title="Cancelled parent")
    orphan = _task(status="rework", title="Orphan rework", assigned=True)
    fresh_inbox = _task(status="inbox", title="Fresh routable inbox")

    action = select_lead_next_action(
        tasks=[parent, orphan, fresh_inbox],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == orphan.id


def test_review_action_still_wins_over_orphan() -> None:
    """An active review task ranks above orphan cleanup — real work first."""
    parent = _task(status="done")
    orphan = _task(status="rework", assigned=True)
    review_task = _task(status="review", title="Real review work")

    action = select_lead_next_action(
        tasks=[parent, orphan, review_task],
        blocked_by_task_id={},
        approval_state_by_task_id={review_task.id: "none"},
        pipeline_missing_by_task_id={},
        review_readiness_by_task_id={review_task.id: {"ready": True}},
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "inspect_review_gates"
    assert action.task_id == review_task.id


def test_orphan_action_skipped_when_orphan_map_empty() -> None:
    inbox_task = _task(status="inbox")

    action = select_lead_next_action(
        tasks=[inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={},
    )

    assert action.action == "route_inbox"


def test_orphan_action_skipped_when_kwarg_omitted() -> None:
    """Backwards-compat: callers that don't pass the orphan map see no
    change in behavior — the kwarg defaults to None."""
    inbox_task = _task(status="inbox")

    action = select_lead_next_action(
        tasks=[inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action == "route_inbox"


def test_orphan_action_uses_lowest_id_for_determinism() -> None:
    parent = _task(status="done")
    # Two orphans with different ids; action should pick the one with the
    # lexicographically smaller string id.
    orphan_a = _task(status="rework", title="A")
    orphan_b = _task(status="inbox", title="B")
    smaller = sorted([orphan_a, orphan_b], key=lambda t: str(t.id))[0]

    action = select_lead_next_action(
        tasks=[parent, orphan_a, orphan_b],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={
            orphan_a.id: parent.id,
            orphan_b.id: parent.id,
        },
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == smaller.id
    assert action.details["orphan_count"] == 2


def test_orphan_with_blocker_still_surfaces() -> None:
    """An orphan child can carry its own waiting flags (open Blocker, pending
    OperatorDecision, etc.) — those don't disqualify it from cleanup. The
    parent terminating already declared the work moot."""
    parent = _task(status="done")
    orphan = _task(status="rework", assigned=True)

    action = select_lead_next_action(
        tasks=[parent, orphan],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_open_blocker=frozenset({orphan.id}),
        orphan_children_with_terminal_parent={orphan.id: parent.id},
    )

    assert action.action == "cancel_orphan_child"
    assert action.task_id == orphan.id


def test_orphan_action_skipped_when_child_already_terminal() -> None:
    """If the orphan map happens to contain a child that's now terminal
    (race between snapshot read and selection), skip it."""
    parent = _task(status="done")
    already_done_child = _task(status="cancelled")

    action = select_lead_next_action(
        tasks=[parent, already_done_child],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        orphan_children_with_terminal_parent={already_done_child.id: parent.id},
    )

    assert action.action == "clear"
