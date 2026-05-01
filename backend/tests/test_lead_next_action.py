# ruff: noqa: INP001
"""Regression tests for deterministic lead next-action selection."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.core.time import utcnow
from app.models.tasks import Task
from app.services.lead_next_action import (
    IN_PROGRESS_PIPELINE_NUDGE_GRACE,
    latest_approval_state_by_task_id,
    select_lead_next_action,
)


def _task(
    *,
    status: str,
    title: str = "Task",
    assigned: bool = False,
    review_packet_type: str | None = None,
    in_progress_at: datetime | None = None,
) -> Task:
    return Task(
        id=uuid4(),
        board_id=uuid4(),
        title=title,
        status=status,
        assigned_agent_id=uuid4() if assigned else None,
        review_packet_type=review_packet_type,
        in_progress_at=in_progress_at,
    )


def _stale_in_progress_at() -> datetime:
    return utcnow() - IN_PROGRESS_PIPELINE_NUDGE_GRACE - timedelta(minutes=5)


def test_selects_approved_review_task_for_gate_inspection_first() -> None:
    task = _task(status="review", title="Ready review")

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={task.id: "approved"},
        pipeline_missing_by_task_id={},
        review_readiness_by_task_id={task.id: {"ready": True}},
    )

    assert action.action_required is True
    assert action.action == "inspect_review_gates"
    assert action.reason_code == "approved_review_needs_done_gate"
    assert action.task_id == task.id
    assert action.details["approval_state"] == "approved"
    assert action.details["review_readiness"] == {"ready": True}


def test_frontend_review_with_missing_pipeline_requires_gate_inspection() -> None:
    task = _task(status="review", title="Frontend review", review_packet_type="frontend_ui")

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={task.id: "none"},
        pipeline_missing_by_task_id={task.id: ["deployed", "runtime_verified"]},
    )

    assert action.action_required is True
    assert action.action == "inspect_review_gates"
    assert action.reason_code == "review_task_missing_gates"
    assert action.task_id == task.id
    assert action.details["approval_state"] == "none"
    assert action.details["missing_pipeline_states"] == ["deployed", "runtime_verified"]


def test_ready_in_progress_frontend_nudges_worker_review_submission() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: []},
    )

    assert action.action_required is True
    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_worker_ready_for_review_submission"
    assert action.task_id == task.id
    assert action.details["pipeline_ready"] is True
    assert action.details["lead_may_not_patch_review"] is True
    assert action.details["next_step"] == "nudge_assigned_worker_to_patch_status_review"


def test_in_progress_frontend_missing_pipeline_names_pipeline_gate() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["runtime_verified"]},
    )

    assert action.action_required is True
    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_pipeline_missing_review_gate"
    assert action.task_id == task.id
    assert action.details["pipeline_ready"] is False
    assert action.details["missing_pipeline_states"] == ["runtime_verified"]
    assert action.details["missing_worker_pipeline_states"] == ["runtime_verified"]
    assert action.details["missing_deploy_pipeline_states"] == []
    assert action.details["next_step"] == "inspect_pipeline_state_not_review_readiness"
    assert action.details["in_progress_grace_minutes"] == int(
        IN_PROGRESS_PIPELINE_NUDGE_GRACE.total_seconds() // 60
    )


def test_in_progress_pipeline_missing_splits_worker_and_deploy_states() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={
            task.id: [
                "code_changed",
                "committed",
                "built",
                "deployed",
                "live_build_verified",
                "runtime_verified",
            ],
        },
    )

    assert action.reason_code == "in_progress_pipeline_missing_review_gate"
    assert action.details["missing_worker_pipeline_states"] == [
        "code_changed",
        "committed",
        "live_build_verified",
        "runtime_verified",
    ]
    assert action.details["missing_deploy_pipeline_states"] == ["built", "deployed"]


def test_fresh_in_progress_frontend_missing_pipeline_skips_nudge() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=utcnow() - timedelta(minutes=5),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["code_changed", "committed"]},
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_waiting_or_no_active_work"


def test_generic_in_progress_grace_skips_nudge_for_fresh_task() -> None:
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=utcnow() - timedelta(minutes=5),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is False
    assert action.action == "clear"


def test_owner_split_includes_default_topology_assumption() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["built", "runtime_verified"]},
    )

    assert action.details["pipeline_owner_assumption"] == "default_openclaw_topology"


def test_unknown_pipeline_state_defaults_to_worker_owner() -> None:
    task = _task(
        status="in_progress",
        title="Frontend implementation",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["unknown_state", "built"]},
    )

    assert action.details["missing_worker_pipeline_states"] == ["unknown_state"]
    assert action.details["missing_deploy_pipeline_states"] == ["built"]


def test_fresh_then_stale_frontend_picks_stale_task() -> None:
    fresh_task = _task(
        status="in_progress",
        title="Fresh frontend",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=utcnow() - timedelta(minutes=2),
    )
    stale_task = _task(
        status="in_progress",
        title="Stale frontend",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[fresh_task, stale_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={
            fresh_task.id: ["code_changed"],
            stale_task.id: ["committed"],
        },
    )

    assert action.task_id == stale_task.id
    assert action.reason_code == "in_progress_pipeline_missing_review_gate"


def test_fresh_in_progress_with_inbox_routes_inbox() -> None:
    fresh_task = _task(
        status="in_progress",
        title="Fresh frontend",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=utcnow() - timedelta(minutes=2),
    )
    inbox_task = _task(status="inbox", title="New work")

    action = select_lead_next_action(
        tasks=[fresh_task, inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={fresh_task.id: ["code_changed"]},
    )

    assert action.action == "route_inbox"
    assert action.task_id == inbox_task.id


def test_in_progress_age_at_grace_boundary_is_stale() -> None:
    fixed_now = utcnow()
    task = _task(
        status="in_progress",
        title="Boundary task",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=fixed_now - IN_PROGRESS_PIPELINE_NUDGE_GRACE,
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["committed"]},
        now=fixed_now,
    )

    assert action.reason_code == "in_progress_pipeline_missing_review_gate"


def test_aware_in_progress_at_with_offset_uses_utc_age() -> None:
    from datetime import UTC, timezone

    fixed_now = utcnow()
    aware_started = (fixed_now - IN_PROGRESS_PIPELINE_NUDGE_GRACE - timedelta(hours=1))
    aware_started = aware_started.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=-3)))
    task = _task(
        status="in_progress",
        title="Aware tz task",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=aware_started,
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={task.id: ["committed"]},
        now=fixed_now,
    )

    assert action.reason_code == "in_progress_pipeline_missing_review_gate"
    expected_minutes = int(
        (IN_PROGRESS_PIPELINE_NUDGE_GRACE + timedelta(hours=1)).total_seconds() // 60
    )
    # Exact minutes — a buggy strip-only normalization would compute the
    # offset (-03:00) into the delta and report ~3h more (260 instead of 80).
    assert action.details["in_progress_minutes"] == expected_minutes


def test_generic_in_progress_past_grace_fires_health_check() -> None:
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is True
    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_work_needs_health_check"
    assert action.details["in_progress_grace_minutes"] == int(
        IN_PROGRESS_PIPELINE_NUDGE_GRACE.total_seconds() // 60
    )


def test_routes_unassigned_inbox_when_no_review_or_active_work_exists() -> None:
    task = _task(status="inbox", title="New work")

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is True
    assert action.action == "route_inbox"
    assert action.reason_code == "unassigned_inbox_needs_routing"
    assert action.task_id == task.id


def test_routes_unassigned_inbox_before_assigned_rework() -> None:
    inbox = _task(status="inbox", title="New inbox")
    rework = _task(status="rework", title="Existing rework", assigned=True)

    action = select_lead_next_action(
        tasks=[rework, inbox],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is True
    assert action.action == "route_inbox"
    assert action.reason_code == "unassigned_inbox_needs_routing"
    assert action.task_id == inbox.id


def test_routes_assigned_inbox_for_lead_triage() -> None:
    """Assigned-inbox tasks now route through ``materialize_decomposition_plan``
    (replaces the old ``assigned_inbox_needs_lead_triage`` action). The new
    tier carries idempotency guards (``tasks_with_children``,
    ``tasks_with_umbrella_retired_marker``) so the lead loop doesn't fire
    the same nudge every heartbeat.
    """
    task = _task(status="inbox", title="Assigned inbox", assigned=True)

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is True
    assert action.action == "materialize_decomposition_plan"
    assert action.reason_code == "inbox_assigned_awaiting_subtask_materialization"
    assert action.task_id == task.id
    assert action.assigned_agent_id == task.assigned_agent_id
    assert action.details["assigned_agent_id"] == str(task.assigned_agent_id)


def test_routes_assigned_inbox_before_assigned_rework() -> None:
    inbox = _task(status="inbox", title="Assigned inbox", assigned=True)
    rework = _task(status="rework", title="Existing rework", assigned=True)

    action = select_lead_next_action(
        tasks=[rework, inbox],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is True
    assert action.action == "materialize_decomposition_plan"
    assert action.reason_code == "inbox_assigned_awaiting_subtask_materialization"
    assert action.task_id == inbox.id


def test_returns_clear_when_only_known_blocked_work_remains() -> None:
    task = _task(status="in_progress", title="Blocked work", assigned=True)

    action = select_lead_next_action(
        tasks=[task],
        blocked_by_task_id={task.id: [uuid4()]},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_waiting_or_no_active_work"


def test_open_structured_blocker_excludes_task_from_active_queue() -> None:
    """A task with an open structured Blocker must not dominate routing.

    Mirrors the read-side blocker model in tasks.py — without this filter,
    a parked task with an open Blocker keeps appearing in the active queue
    and starves inbox routing.
    """
    blocked_task = _task(
        status="in_progress",
        title="In progress with structured blocker",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    inbox_task = _task(status="inbox", title="Unassigned inbox work")

    action = select_lead_next_action(
        tasks=[blocked_task, inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_open_blocker=frozenset({blocked_task.id}),
    )

    assert action.action == "route_inbox"
    assert action.task_id == inbox_task.id


def test_pending_operator_decision_excludes_task_from_active_queue() -> None:
    """A pending OperatorDecision (first-class entity) excludes routing.

    Same contract as the legacy ``operator_decision_required`` boolean flag.
    """
    blocked_task = _task(
        status="in_progress",
        title="In progress with pending operator decision",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    inbox_task = _task(status="inbox", title="Unassigned inbox work")

    action = select_lead_next_action(
        tasks=[blocked_task, inbox_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_pending_operator_decision=frozenset({blocked_task.id}),
    )

    assert action.action == "route_inbox"
    assert action.task_id == inbox_task.id


def test_all_four_blocker_sources_filter_independently() -> None:
    """Each of the four blocker sources independently filters a task."""
    by_dependency = _task(
        status="in_progress", title="dep-blocked", assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_legacy_flag = _task(
        status="in_progress", title="legacy-flag-blocked", assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_legacy_flag.operator_decision_required = True
    by_open_blocker = _task(
        status="in_progress", title="structured-blocker", assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_pending_decision = _task(
        status="in_progress", title="pending-decision", assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    inbox_task = _task(status="inbox", title="Available inbox work")

    action = select_lead_next_action(
        tasks=[by_dependency, by_legacy_flag, by_open_blocker, by_pending_decision, inbox_task],
        blocked_by_task_id={by_dependency.id: [uuid4()]},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_open_blocker=frozenset({by_open_blocker.id}),
        tasks_with_pending_operator_decision=frozenset({by_pending_decision.id}),
    )

    assert action.action == "route_inbox"
    assert action.task_id == inbox_task.id


def test_open_blocker_alone_yields_clear() -> None:
    """A board with only an open-blocker-blocked task and no inbox work
    must return clear — never pick the blocked task as next action."""
    blocked_task = _task(
        status="in_progress",
        title="Only blocked work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        tasks=[blocked_task],
        blocked_by_task_id={},
        approval_state_by_task_id={},
        pipeline_missing_by_task_id={},
        tasks_with_open_blocker=frozenset({blocked_task.id}),
    )

    assert action.action_required is False
    assert action.action == "clear"


def test_latest_approval_state_uses_newest_move_to_done_row() -> None:
    task_id = uuid4()
    old_created = utcnow()
    old_resolved = old_created
    new_created = old_created + timedelta(minutes=1)
    new_resolved = new_created

    state = latest_approval_state_by_task_id(
        task_ids=[task_id],
        rows=[
            (task_id, "approved", old_resolved, old_created),
            (task_id, "rejected", new_resolved, new_created),
        ],
    )

    assert state[task_id] == "rejected"
