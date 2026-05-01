"""Deterministic next-action selection for board lead heartbeats."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from app.core.time import as_naive_utc, utcnow
from app.models.tasks import Task
from app.schemas.lead_actions import LeadNextActionName, LeadNextActionRead
from app.services.parent_cascade import TERMINAL_STATUSES
from app.services.task_pipeline import split_missing_states_by_default_owner

ApprovalState = Literal["none", "pending", "approved", "rejected"]
ApprovalStateRow = tuple[UUID | None, str, datetime | None, datetime]

# Grace window after a worker picks up an in_progress task before the lead is
# nudged to chase missing pipeline events. Avoids premature nudges fired
# seconds-to-minutes after the worker accepts the task and starts coding.
IN_PROGRESS_PIPELINE_NUDGE_GRACE = timedelta(minutes=20)


def latest_approval_state_by_task_id(
    *,
    task_ids: Sequence[UUID],
    rows: Sequence[ApprovalStateRow],
) -> dict[UUID, ApprovalState]:
    """Return the latest relevant approval state for each task."""

    state_by_task_id: dict[UUID, ApprovalState] = {task_id: "none" for task_id in task_ids}
    latest_by_task_id: dict[UUID, tuple[datetime, ApprovalState]] = {}
    for task_id, raw_status, resolved_at, created_at in rows:
        if task_id is None:
            continue
        timestamp = resolved_at or created_at
        current = latest_by_task_id.get(task_id)
        if current is not None and timestamp <= current[0]:
            continue
        if raw_status in {"pending", "approved", "rejected"}:
            latest_by_task_id[task_id] = (timestamp, raw_status)
    for task_id, (_timestamp, approval_status) in latest_by_task_id.items():
        state_by_task_id[task_id] = approval_status
    return state_by_task_id


def _is_waiting(
    task: Task,
    blocked_by_task_id: Mapping[UUID, Sequence[UUID]],
    tasks_with_open_blocker: frozenset[UUID] | set[UUID] = frozenset(),
    tasks_with_pending_operator_decision: frozenset[UUID] | set[UUID] = frozenset(),
) -> bool:
    """A task is "waiting" if any of the four blocker sources apply.

    Mirrors the read-side blocker model in ``backend/app/api/tasks.py``
    (§I1/§I3): unresolved dependency, legacy boolean flag, open structured
    Blocker row, or pending OperatorDecision entity. Lead routing must
    exclude all four — otherwise a parked task with a structured Blocker
    can dominate the active queue and starve inbox routing.
    """
    if task.status in {"done", "cancelled"}:
        return True
    return (
        bool(blocked_by_task_id.get(task.id))
        or bool(task.operator_decision_required)
        or task.id in tasks_with_open_blocker
        or task.id in tasks_with_pending_operator_decision
    )


def _task_sort_key(task: Task) -> tuple[str, str]:
    timestamp = task.updated_at or task.created_at
    return (timestamp.isoformat(), str(task.id))


def _action(
    *,
    task: Task | None,
    action_required: bool,
    action: LeadNextActionName,
    reason_code: str,
    details: dict[str, object] | None = None,
) -> LeadNextActionRead:
    return LeadNextActionRead(
        action_required=action_required,
        action=action,
        reason_code=reason_code,
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
        task_title=task.title if task is not None else None,
        assigned_agent_id=task.assigned_agent_id if task is not None else None,
        details=details or {},
    )


def _review_readiness_ready(readiness: object | None) -> bool:
    return isinstance(readiness, Mapping) and readiness.get("ready") is True


def _in_progress_age(task: Task, *, now: datetime) -> timedelta | None:
    """Age of the task's current in_progress run, or None if never started.

    Both `now` and the resolved start timestamp are normalized to naive UTC
    so the subtraction is correct regardless of whether either input is
    naive (the project convention) or carries an offset.
    """
    started = task.in_progress_at or task.updated_at or task.created_at
    if started is None:
        return None
    return as_naive_utc(now) - as_naive_utc(started)


def _in_progress_is_fresh(
    task: Task,
    *,
    now: datetime,
    grace: timedelta,
) -> bool:
    age = _in_progress_age(task, now=now)
    if age is None:
        return False
    return age < grace


def _in_progress_age_minutes(task: Task, *, now: datetime) -> int | None:
    age = _in_progress_age(task, now=now)
    if age is None:
        return None
    return max(0, int(age.total_seconds() // 60))


def select_lead_next_action(
    *,
    tasks: Sequence[Task],
    blocked_by_task_id: Mapping[UUID, Sequence[UUID]],
    approval_state_by_task_id: Mapping[UUID, ApprovalState],
    pipeline_missing_by_task_id: Mapping[UUID, Sequence[str]],
    review_readiness_by_task_id: Mapping[UUID, object] | None = None,
    tasks_with_open_blocker: frozenset[UUID] | set[UUID] | None = None,
    tasks_with_pending_operator_decision: frozenset[UUID] | set[UUID] | None = None,
    orphan_children_with_terminal_parent: Mapping[UUID, UUID] | None = None,
    tasks_with_children: frozenset[UUID] | set[UUID] | None = None,
    now: datetime | None = None,
) -> LeadNextActionRead:
    """Return the single closest-to-done lead action from structured state."""

    if now is None:
        now = utcnow()
    if tasks_with_open_blocker is None:
        tasks_with_open_blocker = frozenset()
    if tasks_with_pending_operator_decision is None:
        tasks_with_pending_operator_decision = frozenset()

    active_tasks = [
        task
        for task in tasks
        if task.status in {"inbox", "in_progress", "review", "rework"}
        and not _is_waiting(
            task,
            blocked_by_task_id,
            tasks_with_open_blocker,
            tasks_with_pending_operator_decision,
        )
    ]
    ordered = sorted(active_tasks, key=_task_sort_key)
    review_readiness_by_task_id = review_readiness_by_task_id or {}

    for task in ordered:
        if task.status != "review":
            continue
        if approval_state_by_task_id.get(task.id, "none") == "approved":
            return _action(
                task=task,
                action_required=True,
                action="inspect_review_gates",
                reason_code="approved_review_needs_done_gate",
                details={
                    "approval_state": "approved",
                    "review_readiness": review_readiness_by_task_id.get(task.id),
                },
            )

    for task in ordered:
        if task.status != "review":
            continue
        approval_state = approval_state_by_task_id.get(task.id, "none")
        readiness = review_readiness_by_task_id.get(task.id)
        missing_pipeline = list(pipeline_missing_by_task_id.get(task.id, []))
        if (
            approval_state == "none"
            and _review_readiness_ready(readiness)
            and not missing_pipeline
        ):
            return _action(
                task=task,
                action_required=True,
                action="inspect_review_gates",
                reason_code="review_task_ready_for_approval",
                details={
                    "approval_state": approval_state,
                    "missing_pipeline_states": missing_pipeline,
                    "review_packet_type": task.review_packet_type,
                    "validation_target": task.validation_target,
                    "review_readiness": readiness,
                },
            )

    for task in ordered:
        if task.status != "review":
            continue
        approval_state = approval_state_by_task_id.get(task.id, "none")
        # Pending approvals are operator-owned: the lead has no
        # further action until the operator approves, rejects, or
        # cancels. Falling through unblocks lower-tier work
        # (orphan cleanup, rework follow-up, inbox routing) so the
        # heartbeat drain loop doesn't trap on the same review every
        # tick. ``approved`` is handled by the earlier tier 1 loop;
        # everything else (``none`` without readiness, ``rejected``,
        # missing pipeline) is genuine lead-actionable friction.
        if approval_state == "pending":
            continue
        missing_pipeline = list(pipeline_missing_by_task_id.get(task.id, []))
        return _action(
            task=task,
            action_required=True,
            action="inspect_review_gates",
            reason_code="review_task_missing_gates",
            details={
                "approval_state": approval_state,
                "missing_pipeline_states": missing_pipeline,
                "review_packet_type": task.review_packet_type,
                "validation_target": task.validation_target,
                "review_readiness": review_readiness_by_task_id.get(task.id),
            },
        )

    for task in ordered:
        if task.status != "in_progress" or task.assigned_agent_id is None:
            continue
        if task.id not in pipeline_missing_by_task_id:
            continue
        missing_pipeline = list(pipeline_missing_by_task_id.get(task.id, []))
        if not missing_pipeline:
            return _action(
                task=task,
                action_required=True,
                action="inspect_stale_in_progress",
                reason_code="in_progress_worker_ready_for_review_submission",
                details={
                    "review_packet_type": task.review_packet_type,
                    "validation_target": task.validation_target,
                    "pipeline_ready": True,
                    "missing_pipeline_states": [],
                    "missing_worker_pipeline_states": [],
                    "missing_deploy_pipeline_states": [],
                    "in_progress_minutes": _in_progress_age_minutes(task, now=now),
                    "next_step": "nudge_assigned_worker_to_patch_status_review",
                    "lead_may_not_patch_review": True,
                },
            )
        if _in_progress_is_fresh(
            task,
            now=now,
            grace=IN_PROGRESS_PIPELINE_NUDGE_GRACE,
        ):
            continue
        owner_split = split_missing_states_by_default_owner(missing_pipeline)
        return _action(
            task=task,
            action_required=True,
            action="inspect_stale_in_progress",
            reason_code="in_progress_pipeline_missing_review_gate",
            details={
                "pipeline_ready": False,
                "missing_pipeline_states": missing_pipeline,
                "missing_worker_pipeline_states": owner_split.worker,
                "missing_deploy_pipeline_states": owner_split.deploy,
                "pipeline_owner_assumption": "default_openclaw_topology",
                "review_packet_type": task.review_packet_type,
                "validation_target": task.validation_target,
                "in_progress_minutes": _in_progress_age_minutes(task, now=now),
                "in_progress_grace_minutes": int(
                    IN_PROGRESS_PIPELINE_NUDGE_GRACE.total_seconds() // 60
                ),
                "next_step": "inspect_pipeline_state_not_review_readiness",
            },
        )

    # Phase V — orphan children of terminal parents. Surface BEFORE
    # rework/inbox routing so the lead retires obsolete decomposition
    # children rather than nudging owners to keep working on them.
    # Iterates the full ``tasks`` list (not ``ordered``) because an
    # orphan child can carry its own waiting flags — those don't
    # disqualify cleanup; the parent terminating already declared the
    # work moot. Orphans currently in ``review`` or ``in_progress``
    # are left to complete naturally — earlier branches will have
    # surfaced those if they need attention. Already-terminal orphans
    # are skipped (race-safe: snapshot may include a child that
    # transitioned during the tick). Sorted by id (not timestamp like
    # ``_task_sort_key``) because cleanup ordering is arbitrary as
    # long as it is deterministic across calls within the same tick.
    if orphan_children_with_terminal_parent:
        orphan_candidates = sorted(
            (
                task for task in tasks
                if task.id in orphan_children_with_terminal_parent
                and task.status not in TERMINAL_STATUSES
                and task.status not in {"review", "in_progress"}
            ),
            key=lambda t: str(t.id),
        )
        if orphan_candidates:
            orphan_task = orphan_candidates[0]
            parent_id = orphan_children_with_terminal_parent[orphan_task.id]
            return _action(
                task=orphan_task,
                action_required=True,
                action="cancel_orphan_child",
                reason_code="non_terminal_child_of_terminal_parent",
                details={
                    "parent_task_id": str(parent_id),
                    "orphan_count": len(orphan_candidates),
                },
            )

    for task in ordered:
        if task.status == "rework" and task.assigned_agent_id is not None:
            return _action(
                task=task,
                action_required=True,
                action="route_rework",
                reason_code="assigned_rework_needs_owner_followup",
            )

    for task in ordered:
        if task.status != "in_progress" or task.assigned_agent_id is None:
            continue
        if _in_progress_is_fresh(
            task,
            now=now,
            grace=IN_PROGRESS_PIPELINE_NUDGE_GRACE,
        ):
            continue
        return _action(
            task=task,
            action_required=True,
            action="inspect_stale_in_progress",
            reason_code="in_progress_work_needs_health_check",
            details={
                "in_progress_minutes": _in_progress_age_minutes(task, now=now),
                "in_progress_grace_minutes": int(
                    IN_PROGRESS_PIPELINE_NUDGE_GRACE.total_seconds() // 60
                ),
            },
        )

    for task in ordered:
        if task.status == "inbox" and task.assigned_agent_id is None:
            return _action(
                task=task,
                action_required=True,
                action="route_inbox",
                reason_code="unassigned_inbox_needs_routing",
            )

    # Tier (last before clear) — inbox tasks already assigned to a
    # reviewer/architect awaiting Supervisor materialization. The
    # ``lead-inbox-routing`` decomposition handshake is: (1) lead
    # assigns task to Architect, (2) Architect posts decomposition
    # plan as a comment, (3) lead reads plan and creates parent-linked
    # subtasks, (4) lead retires the umbrella. Without a tier here,
    # step (3) never gets surfaced to the lead via ``/lead/next-action``
    # because tier 9 (``route_inbox``) requires ``assigned_agent_id IS
    # NULL``. Tasks would sit in inbox-with-Architect-assigned forever.
    # The ``tasks_with_children`` set lets us skip already-materialized
    # parents (idempotency).
    if tasks_with_children is None:
        tasks_with_children = frozenset()
    for task in ordered:
        if task.status != "inbox" or task.assigned_agent_id is None:
            continue
        if task.id in tasks_with_children:
            continue
        return _action(
            task=task,
            action_required=True,
            action="materialize_decomposition_plan",
            reason_code="inbox_assigned_awaiting_subtask_materialization",
            details={
                "assigned_agent_id": str(task.assigned_agent_id),
            },
        )

    return _action(
        task=None,
        action_required=False,
        action="clear",
        reason_code="only_waiting_or_no_active_work",
    )
