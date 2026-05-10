# ruff: noqa: INP001
"""Regression tests for deterministic lead next-action selection."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.core.time import utcnow
from app.models.tasks import Task
from app.services.lead_next_action import (
    IN_PROGRESS_PIPELINE_NUDGE_GRACE,
    LeadInputs,
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={task.id: "approved"},
            pipeline_missing_by_task_id={},
            review_readiness_by_task_id={task.id: {"ready": True}},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={task.id: "none"},
            pipeline_missing_by_task_id={task.id: ["deployed", "runtime_verified"]},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: []},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["runtime_verified"]},
        ),
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
        LeadInputs(
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
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["code_changed", "committed"]},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_fresh_in_progress"
    assert action.details["fresh_in_progress_count"] == 1
    assert action.details["active_state_count"] == 1


def test_generic_in_progress_grace_skips_nudge_for_fresh_task() -> None:
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=utcnow() - timedelta(minutes=5),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["built", "runtime_verified"]},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["unknown_state", "built"]},
        ),
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
        LeadInputs(
            tasks=[fresh_task, stale_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={
                fresh_task.id: ["code_changed"],
                stale_task.id: ["committed"],
            },
        ),
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
        LeadInputs(
            tasks=[fresh_task, inbox_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={fresh_task.id: ["code_changed"]},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["committed"]},
        ),
        now=fixed_now,
    )

    assert action.reason_code == "in_progress_pipeline_missing_review_gate"


def test_aware_in_progress_at_with_offset_uses_utc_age() -> None:
    from datetime import UTC, timezone

    fixed_now = utcnow()
    aware_started = fixed_now - IN_PROGRESS_PIPELINE_NUDGE_GRACE - timedelta(hours=1)
    aware_started = aware_started.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=-3)))
    task = _task(
        status="in_progress",
        title="Aware tz task",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=aware_started,
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["committed"]},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is True
    assert action.action == "route_inbox"
    assert action.reason_code == "unassigned_inbox_needs_routing"
    assert action.task_id == task.id


def test_routes_unassigned_inbox_before_assigned_rework() -> None:
    inbox = _task(status="inbox", title="New inbox")
    rework = _task(status="rework", title="Existing rework", assigned=True)

    action = select_lead_next_action(
        LeadInputs(
            tasks=[rework, inbox],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
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
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
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
        LeadInputs(
            tasks=[rework, inbox],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is True
    assert action.action == "materialize_decomposition_plan"
    assert action.reason_code == "inbox_assigned_awaiting_subtask_materialization"
    assert action.task_id == inbox.id


def test_returns_clear_when_only_known_blocked_work_remains() -> None:
    task = _task(status="in_progress", title="Blocked work", assigned=True)

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={task.id: [uuid4()]},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_blocked"
    assert action.details["blocked_count"] == 1
    assert action.details["active_state_count"] == 1


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
        LeadInputs(
            tasks=[blocked_task, inbox_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({blocked_task.id}),
        ),
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
        LeadInputs(
            tasks=[blocked_task, inbox_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_pending_operator_decision=frozenset({blocked_task.id}),
        ),
    )

    assert action.action == "route_inbox"
    assert action.task_id == inbox_task.id


def test_all_four_blocker_sources_filter_independently() -> None:
    """Each of the four blocker sources independently filters a task."""
    by_dependency = _task(
        status="in_progress",
        title="dep-blocked",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_legacy_flag = _task(
        status="in_progress",
        title="legacy-flag-blocked",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_legacy_flag.operator_decision_required = True
    by_open_blocker = _task(
        status="in_progress",
        title="structured-blocker",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    by_pending_decision = _task(
        status="in_progress",
        title="pending-decision",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    inbox_task = _task(status="inbox", title="Available inbox work")

    action = select_lead_next_action(
        LeadInputs(
            tasks=[by_dependency, by_legacy_flag, by_open_blocker, by_pending_decision, inbox_task],
            blocked_by_task_id={by_dependency.id: [uuid4()]},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({by_open_blocker.id}),
            tasks_with_pending_operator_decision=frozenset({by_pending_decision.id}),
        ),
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
        LeadInputs(
            tasks=[blocked_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({blocked_task.id}),
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"


def test_clear_no_active_work_when_only_terminal_tasks_exist() -> None:
    done_task = _task(status="done", title="Already done")
    cancelled_task = _task(status="cancelled", title="Already cancelled")

    action = select_lead_next_action(
        LeadInputs(
            tasks=[done_task, cancelled_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "no_active_work"
    assert action.details["active_state_count"] == 0


def test_clear_no_active_work_when_tasks_list_is_empty() -> None:
    action = select_lead_next_action(
        LeadInputs(
            tasks=[],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "no_active_work"


def test_clear_only_pending_approval_when_review_awaits_operator() -> None:
    review_task = _task(status="review", title="Awaiting operator approval")

    action = select_lead_next_action(
        LeadInputs(
            tasks=[review_task],
            blocked_by_task_id={},
            approval_state_by_task_id={review_task.id: "pending"},
            pipeline_missing_by_task_id={},
            review_readiness_by_task_id={review_task.id: {"ready": True}},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_pending_approval"
    assert action.details["pending_approval_count"] == 1


def test_clear_mixed_pending_approval_and_blocked_uses_legacy_fallback() -> None:
    """``only_X`` reason_codes are strict — full active set must match.

    A board with one pending-approval review + one blocked in_progress is
    NEITHER ``only_pending_approval`` NOR ``only_blocked``, so the gate
    must return the legacy umbrella code. ``details`` carries the breakdown
    so the operator can still see what's parked.
    """
    pending_review = _task(status="review", title="Pending approval")
    blocked_in_progress = _task(
        status="in_progress",
        title="Blocked work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[pending_review, blocked_in_progress],
            blocked_by_task_id={},
            approval_state_by_task_id={pending_review.id: "pending"},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({blocked_in_progress.id}),
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_waiting_or_no_active_work"
    assert action.details["pending_approval_count"] == 1
    assert action.details["blocked_count"] == 1
    assert action.details["fresh_in_progress_count"] == 0
    assert action.details["active_state_count"] == 2
    assert action.details["other_active_count"] == 0


def test_clear_mixed_blocked_and_fresh_in_progress_uses_legacy_fallback() -> None:
    blocked_task = _task(status="in_progress", title="Blocked", assigned=True)
    fresh_task = _task(
        status="in_progress",
        title="Fresh",
        assigned=True,
        in_progress_at=utcnow() - timedelta(minutes=5),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[blocked_task, fresh_task],
            blocked_by_task_id={blocked_task.id: [uuid4()]},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_waiting_or_no_active_work"
    assert action.details["blocked_count"] == 1
    assert action.details["fresh_in_progress_count"] == 1


def test_clear_only_pending_approval_with_multiple_pending_reviews() -> None:
    review_a = _task(status="review", title="Pending A")
    review_b = _task(status="review", title="Pending B")

    action = select_lead_next_action(
        LeadInputs(
            tasks=[review_a, review_b],
            blocked_by_task_id={},
            approval_state_by_task_id={
                review_a.id: "pending",
                review_b.id: "pending",
            },
            pipeline_missing_by_task_id={},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"
    assert action.reason_code == "only_pending_approval"
    assert action.details["pending_approval_count"] == 2
    assert action.details["active_state_count"] == 2


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


def _stale_blocker_age_at() -> datetime:
    """Datetime guaranteed older than the stale-blocker grace window."""
    from app.services.lead_next_action import STALE_BLOCKER_NUDGE_GRACE

    return utcnow() - STALE_BLOCKER_NUDGE_GRACE - timedelta(minutes=5)


def _fresh_blocker_age_at() -> datetime:
    return utcnow() - timedelta(minutes=2)


def test_inspect_stale_blocker_ignores_self_ack_by_lead() -> None:
    """Codex review 2026-05-04: skill-doc-only prevention of lead
    self-ack is insufficient because cached prompts may miss the
    new rule. Code-level guard: when the acker IS the lead agent,
    treat the blocker as if not acknowledged (effective age =
    created_at). This catches the production loop where Supervisor
    self-ack'd both parent blocker 64c0d937 and AC6 child blocker
    f7529869 to silence the gate temporarily, then re-fired every
    grace cycle.
    """
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Self-acked by lead, should still fire stale",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    lead_id = uuid4()
    blocker_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="deploy_drift",
        owner_role="DevOps",
        acknowledged_by_agent_id=lead_id,  # lead acked
        created_at=_stale_blocker_age_at(),  # past grace
        acknowledged_at=utcnow() - timedelta(minutes=2),  # fresh ack
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
            lead_agent_id=lead_id,
        ),
    )

    # Despite the fresh ack, the tier fires because the acker was the
    # lead themselves — the misuse pattern. The lead is routed back
    # to the actual owner_role (DevOps).
    assert action.action == "inspect_stale_blocker"
    assert action.reason_code == "stale_open_blocker_needs_owner_followup"


def test_inspect_stale_blocker_respects_owner_ack() -> None:
    """Counterpart to the lead-self-ack test: when the acker is the
    OWNER (not the lead), the ack is legitimate and resets the
    grace clock as designed."""
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Acked by owner, should NOT fire stale",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    lead_id = uuid4()
    owner_id = uuid4()
    blocker_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="deploy_drift",
        owner_role="DevOps",
        acknowledged_by_agent_id=owner_id,  # owner acked, not lead
        created_at=_stale_blocker_age_at(),
        acknowledged_at=utcnow() - timedelta(minutes=2),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
            lead_agent_id=lead_id,
        ),
    )

    assert (
        action.action != "inspect_stale_blocker"
    ), f"owner-acked blocker still fired stale; action={action.action}"


def test_inspect_stale_blocker_resets_clock_on_acknowledgement() -> None:
    """Production gap 2026-05-04 (parent QA gate AC6 blocker 64c0d937):
    Supervisor acknowledged the blocker, but the stale-blocker tier
    kept firing because the comparison only checked ``created_at``.
    The lead then re-nudged on every heartbeat, bursting POST /comments
    past the per-IP rate-limit and getting 429s.

    Acknowledgement is the explicit "owner is on it" signal — it
    should reset the stale clock so the lead waits ANOTHER grace
    window before re-nudging. If the owner goes silent post-ack,
    the tier still fires (defensively), but only after the new window.
    """
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Acknowledged blocker, owner on it",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    blocker_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="deploy_drift",
        owner_role="DevOps",
        acknowledged_by_agent_id=uuid4(),
        created_at=_stale_blocker_age_at(),
    )
    # Override the NamedTuple's missing acknowledged_at field by extending the type.
    # If the production OpenBlockerRow doesn't carry acknowledged_at, the test
    # fails at construction — that fail tells us we need to add it.
    fresh_ack_at = utcnow() - timedelta(minutes=2)
    blocker_row = blocker_row._replace()  # baseline shape
    # Construct the variant that carries the ack timestamp:
    object.__setattr__ if False else None  # keep linter quiet
    # Use field-by-field new instance (NamedTuple doesn't accept arbitrary kwargs):
    fields = {
        "id": blocker_row.id,
        "reason_code": blocker_row.reason_code,
        "owner_role": blocker_row.owner_role,
        "acknowledged_by_agent_id": blocker_row.acknowledged_by_agent_id,
        "created_at": blocker_row.created_at,
        "acknowledged_at": fresh_ack_at,
    }
    blocker_row = OpenBlockerRow(**fields)

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
        ),
    )

    # Acknowledgement is fresh; stale tier should NOT fire on this task.
    # The lead falls through to other tiers (no inbox routing here either,
    # so the action should be ``clear`` — owner has the ack and is working).
    assert action.action != "inspect_stale_blocker", (
        f"acknowledged blocker still firing stale tier; action={action.action} "
        f"reason={action.reason_code}"
    )


def test_inspect_stale_blocker_re_fires_when_acknowledgement_aged() -> None:
    """Counterpart to the ack-resets-clock test: if the owner ACKed but
    then went silent past the grace window, the tier must fire again so
    the lead can chase. Acknowledgement is a fresh-clock signal, not a
    permanent silencer."""
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Acknowledged but owner silent",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    blocker_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="deploy_drift",
        owner_role="DevOps",
        acknowledged_by_agent_id=uuid4(),
        created_at=_stale_blocker_age_at(),
        acknowledged_at=_stale_blocker_age_at(),  # ack itself is past grace
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
        ),
    )

    assert action.action == "inspect_stale_blocker"
    assert action.reason_code == "stale_open_blocker_needs_owner_followup"


def test_inspect_stale_blocker_tolerates_tz_aware_created_at() -> None:
    """Production gap 2026-05-04 (request 2f667e65): the lead-next-action
    endpoint returned 500 with ``TypeError: can't compare offset-naive
    and offset-aware datetimes`` because PostgreSQL ``TIMESTAMP WITH TIME
    ZONE`` columns return tz-aware datetimes via asyncpg, while
    ``utcnow()`` is tz-naive. The stale-blocker tier compared
    ``blocker.created_at < (now - GRACE)`` and crashed.

    Cover both comparison sites (line 475 and line 504 in lead_next_action.py)
    by feeding an OpenBlockerRow whose ``created_at`` carries ``tzinfo=UTC``.
    The selector must coerce to a comparable shape and not raise.
    """
    from datetime import UTC

    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Blocked with tz-aware blocker",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    blocker_id = uuid4()
    aware_created_at = (utcnow() - timedelta(hours=1)).replace(tzinfo=UTC)
    blocker_row = OpenBlockerRow(
        id=blocker_id,
        reason_code="operator_reject_demo",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=aware_created_at,
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
        ),
    )

    assert action.action == "inspect_stale_blocker"
    assert action.details["oldest_blocker_age_minutes"] >= 0


def test_inspect_stale_blocker_fires_for_aged_blocker_on_active_task() -> None:
    """Phase V §I9 Fix 3: blocked tasks aged past the stale-blocker
    grace window must surface as ``inspect_stale_blocker`` so the lead
    drain loop can nudge the owner. Without this, ``_is_waiting()``
    filters blocked tasks out of ``active_tasks`` and the lead has no
    actionable signal — AC5 sat blocked + invisible for ~12h.
    """
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Blocked beyond grace",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    blocker_id = uuid4()
    blocker_row = OpenBlockerRow(
        id=blocker_id,
        reason_code="pipeline_missing_review_gate",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=_stale_blocker_age_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [blocker_row]},
        ),
    )

    assert action.action_required is True
    assert action.action == "inspect_stale_blocker"
    assert action.reason_code == "stale_open_blocker_needs_owner_followup"
    assert action.task_id == task.id
    assert action.details["blocker_count"] == 1
    assert action.details["blocker_ids"] == [str(blocker_id)]
    assert action.details["reason_codes"] == ["pipeline_missing_review_gate"]
    assert action.details["owner_role"] == "Programmer-Frontend"


def test_inspect_stale_blocker_skips_blocker_within_grace() -> None:
    """A freshly-opened Blocker (<20min) must NOT trigger the stale tier
    — the owner deserves time to act before the lead nudges. Falls
    through to the legacy clear path since the task is otherwise
    filtered out of active_tasks by ``_is_waiting``."""
    from app.services.lead_next_action import OpenBlockerRow

    task = _task(
        status="in_progress",
        title="Blocked within grace",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    fresh_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="pipeline_missing_review_gate",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=_fresh_blocker_age_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({task.id}),
            open_blockers_by_task_id={task.id: [fresh_row]},
        ),
    )

    assert action.action_required is False
    assert action.action == "clear"


def test_inspect_stale_blocker_takes_precedence_over_route_inbox() -> None:
    """Stale-blocker tier should fire before unassigned-inbox routing
    so the lead unsticks blocked work first — a stuck blocked task is
    closer-to-done than a fresh untriaged inbox arrival."""
    from app.services.lead_next_action import OpenBlockerRow

    blocked_task = _task(
        status="in_progress",
        title="Stale blocked task",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    inbox_task = _task(status="inbox", title="Fresh unassigned inbox")
    stale_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="pipeline_missing_review_gate",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=_stale_blocker_age_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[blocked_task, inbox_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({blocked_task.id}),
            open_blockers_by_task_id={blocked_task.id: [stale_row]},
        ),
    )

    assert action.action == "inspect_stale_blocker"
    assert action.task_id == blocked_task.id


def test_inspect_stale_blocker_yields_to_inspect_review_gates() -> None:
    """Active actionable review work (not blocked) keeps precedence.
    Stale-blocker tier is for cleaning up parked work, not jumping in
    front of normal review routing."""
    from app.services.lead_next_action import OpenBlockerRow

    review_task = _task(status="review", title="Approved review awaiting done")
    blocked_task = _task(
        status="in_progress",
        title="Stale blocked task",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    stale_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="pipeline_missing_review_gate",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=_stale_blocker_age_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[review_task, blocked_task],
            blocked_by_task_id={},
            approval_state_by_task_id={review_task.id: "approved"},
            pipeline_missing_by_task_id={},
            review_readiness_by_task_id={review_task.id: {"ready": True}},
            tasks_with_open_blocker=frozenset({blocked_task.id}),
            open_blockers_by_task_id={blocked_task.id: [stale_row]},
        ),
    )

    assert action.action == "inspect_review_gates"
    assert action.task_id == review_task.id


def test_inspect_stale_blocker_skips_terminal_tasks() -> None:
    """Tasks already in ``done`` or ``cancelled`` aren't candidates for
    nudging even if they have lingering open Blockers. Those rows are
    cleanup debt, not active work."""
    from app.services.lead_next_action import OpenBlockerRow

    done_task = _task(status="done", title="Done with stale blocker")
    stale_row = OpenBlockerRow(
        id=uuid4(),
        reason_code="pipeline_missing_review_gate",
        owner_role="Programmer-Frontend",
        acknowledged_by_agent_id=None,
        created_at=_stale_blocker_age_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[done_task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            tasks_with_open_blocker=frozenset({done_task.id}),
            open_blockers_by_task_id={done_task.id: [stale_row]},
        ),
    )

    assert action.action == "clear"


# ---------------------------------------------------------------------------
# Slice 5: gateway_session_state surfaced in inspect_stale_in_progress
# ---------------------------------------------------------------------------


def _gateway_state(
    *,
    agent_id: str = "mc-placeholder",
    last_changed_at_ms: int = 1_777_823_446_849,
    last_phase: str | None = "message",
    aborted_last_run: bool = False,
    session_id: str = "session-uuid-placeholder",
):
    """Build a GatewaySessionState row stub. Imports the SQLModel
    locally so the rest of the test file stays import-light."""
    from app.models.gateway_session_state import GatewaySessionState

    return GatewaySessionState(
        agent_id=agent_id,
        session_label="main",
        session_id=session_id,
        last_phase=last_phase,
        last_message_seq=158,
        last_changed_at_ms=last_changed_at_ms,
        input_tokens=49_931,
        output_tokens=14_736,
        total_tokens=64_667,
        channel="webchat",
        aborted_last_run=aborted_last_run,
    )


def test_stale_in_progress_health_check_surfaces_gateway_state() -> None:
    """When the lead is asked to inspect a stale in-progress task and
    the worker has projected gateway state, the action details must
    include last_changed_at_ms / aborted_last_run so the lead can
    distinguish "agent is silent on the gateway" from "agent is
    actively working but the task DB hasn't been moved"."""
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )
    gateway_state = _gateway_state(
        agent_id=f"mc-{task.assigned_agent_id}",
        last_changed_at_ms=1_777_900_000_000,
        last_phase="tool",
        aborted_last_run=False,
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            gateway_session_by_agent_id={task.assigned_agent_id: gateway_state},
        ),
    )

    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_work_needs_health_check"
    gateway = action.details["gateway_session"]
    assert gateway["last_changed_at_ms"] == 1_777_900_000_000
    assert gateway["last_phase"] == "tool"
    assert gateway["aborted_last_run"] is False
    assert gateway["session_id"] == "session-uuid-placeholder"


def test_stale_in_progress_health_check_marks_gateway_state_absent() -> None:
    """When the projector hasn't seen the assigned agent yet (subscriber
    just started, or the agent never opened a gateway session), the
    action details must explicitly say so — not silently omit. The
    lead playbook needs to distinguish "no signal" from "fresh signal"."""
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
            gateway_session_by_agent_id={},
        ),
    )

    assert action.action == "inspect_stale_in_progress"
    assert action.details["gateway_session"] is None


def test_stale_in_progress_pipeline_missing_surfaces_gateway_state() -> None:
    """The pipeline-missing variant of inspect_stale_in_progress also
    benefits from gateway state — if the agent went silent, that's WHY
    the pipeline events haven't landed yet."""
    task = _task(
        status="in_progress",
        title="Frontend work",
        assigned=True,
        review_packet_type="frontend_ui",
        in_progress_at=_stale_in_progress_at(),
    )
    gateway_state = _gateway_state(
        agent_id=f"mc-{task.assigned_agent_id}",
        last_changed_at_ms=1_777_500_000_000,
        last_phase="message",
        aborted_last_run=True,
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: ["deployed"]},
            gateway_session_by_agent_id={task.assigned_agent_id: gateway_state},
        ),
    )

    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_pipeline_missing_review_gate"
    assert action.details["gateway_session"]["aborted_last_run"] is True
    assert action.details["gateway_session"]["last_phase"] == "message"


def test_in_progress_ready_for_review_surfaces_gateway_state() -> None:
    """The ready-for-review-submission variant — agent has all pipeline
    events but hasn't patched status. Gateway state tells the lead
    whether the agent is silent (so nudge them) or just slow."""
    task = _task(
        status="in_progress",
        title="Frontend work",
        assigned=True,
        review_packet_type="frontend_ui",
    )
    gateway_state = _gateway_state(
        agent_id=f"mc-{task.assigned_agent_id}",
        last_changed_at_ms=1_777_950_000_000,
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={task.id: []},  # ready: empty list, not missing
            gateway_session_by_agent_id={task.assigned_agent_id: gateway_state},
        ),
    )

    assert action.action == "inspect_stale_in_progress"
    assert action.reason_code == "in_progress_worker_ready_for_review_submission"
    assert action.details["gateway_session"]["last_changed_at_ms"] == 1_777_950_000_000


def test_omitting_gateway_session_param_preserves_existing_behavior() -> None:
    """gateway_session_by_agent_id is optional; callers that don't pass
    it (existing tests, tooling) get back details WITHOUT a gateway_session
    key — additive contract, no churn."""
    task = _task(
        status="in_progress",
        title="Backend work",
        assigned=True,
        in_progress_at=_stale_in_progress_at(),
    )

    action = select_lead_next_action(
        LeadInputs(
            tasks=[task],
            blocked_by_task_id={},
            approval_state_by_task_id={},
            pipeline_missing_by_task_id={},
        ),
    )

    assert "gateway_session" not in action.details
