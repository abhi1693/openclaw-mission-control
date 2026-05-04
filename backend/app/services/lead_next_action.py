"""Deterministic next-action selection for board lead heartbeats."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, NamedTuple
from uuid import UUID

from app.core.time import as_naive_utc, utcnow
from app.models.gateway_session_state import GatewaySessionState
from app.models.tasks import Task
from app.schemas.lead_actions import LeadNextActionName, LeadNextActionRead
from app.services.parent_cascade import TERMINAL_STATUSES
from app.services.task_pipeline import split_missing_states_by_default_owner

ApprovalState = Literal["none", "pending", "approved", "rejected"]
ApprovalStateRow = tuple[UUID | None, str, datetime | None, datetime]


class OpenBlockerRow(NamedTuple):
    """Minimal projection of an open ``Blocker`` for the lead gate.

    Phase V §I9 Fix 3 introduced this richer projection because the
    stale-blocker tier needs ``created_at`` (to compute age vs. grace
    window) and owner attribution (to surface who should resolve it)
    — the prior ``tasks_with_open_blocker: frozenset[UUID]`` only
    carried task ids and was insufficient.

    ``acknowledged_at`` is the timestamp the owner accepted the
    blocker (PATCH ``status_transition=acknowledge``). When non-null,
    the stale-blocker tier resets its clock against the ack time
    instead of ``created_at`` — once the owner has explicitly claimed
    the work, the lead waits another grace window before re-nudging.
    Production gap 2026-05-04 (parent QA gate AC6 blocker 64c0d937):
    Supervisor acknowledged the blocker but the tier kept firing
    because ack was ignored, bursting the comment endpoint past the
    per-IP rate-limit.
    """

    id: UUID
    reason_code: str | None
    owner_role: str | None
    acknowledged_by_agent_id: UUID | None
    created_at: datetime
    acknowledged_at: datetime | None = None


@dataclass(frozen=True)
class LeadInputs:
    """Bundle of board-state inputs to ``select_lead_next_action``.

    Codex review of slices 4-5 flagged the selector's 13-kwarg signature
    as past readable. The bundle keeps each field individually
    documentable, lets the API handler pass the inputs as one named
    object (``select_lead_next_action(inputs)``), and means the next
    signal added doesn't bloat the function signature further. Optional
    fields default to empty containers / ``None`` so callers only spell
    out the inputs they actually have."""

    tasks: Sequence[Task]
    blocked_by_task_id: Mapping[UUID, Sequence[UUID]]
    approval_state_by_task_id: Mapping[UUID, ApprovalState]
    pipeline_missing_by_task_id: Mapping[UUID, Sequence[str]]
    review_readiness_by_task_id: Mapping[UUID, object] | None = None
    tasks_with_open_blocker: frozenset[UUID] | set[UUID] | None = None
    tasks_with_pending_operator_decision: frozenset[UUID] | set[UUID] | None = None
    orphan_children_with_terminal_parent: Mapping[UUID, UUID] | None = None
    tasks_with_children: frozenset[UUID] | set[UUID] | None = None
    tasks_with_umbrella_retired_marker: frozenset[UUID] | set[UUID] | None = None
    open_blockers_by_task_id: Mapping[UUID, Sequence[OpenBlockerRow]] | None = None
    gateway_session_by_agent_id: Mapping[UUID, GatewaySessionState] | None = None
    # Verified lead agent id for the current request (per
    # ``_require_board_lead`` upstream). When non-null, the
    # stale-blocker tier ignores ``acknowledged_at`` on blockers
    # acked by this id — lead self-ack on a worker-owned blocker is
    # a misuse pattern that just resets the grace clock without
    # actually progressing the work. Codex review 2026-05-04 caught
    # the production loop. Optional so legacy/test callers without
    # an authenticated lead still work; in that mode self-ack
    # detection is disabled.
    lead_agent_id: UUID | None = None


# Grace window after a worker picks up an in_progress task before the lead is
# nudged to chase missing pipeline events. Avoids premature nudges fired
# seconds-to-minutes after the worker accepts the task and starts coding.
IN_PROGRESS_PIPELINE_NUDGE_GRACE = timedelta(minutes=20)

# Phase V §I9 Fix 3 — grace window for the stale-blocker tier. AC5
# incident showed blocked tasks become invisible to the lead's drain
# loop (``_is_waiting`` filters them out of ``active_tasks``), so the
# new tier surfaces them after this delay. Aligned with the existing
# in-progress nudge grace so owners aren't double-pinged on the same
# clock.
STALE_BLOCKER_NUDGE_GRACE = timedelta(minutes=20)


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


_GATEWAY_SESSION_DETAIL_FIELDS = frozenset(
    {"session_id", "last_phase", "last_changed_at_ms", "aborted_last_run"}
)


def _gateway_session_details(
    task: Task,
    gateway_session_by_agent_id: Mapping[UUID, GatewaySessionState],
) -> dict[str, object] | None:
    """Format a slice-4 GatewaySessionState row for inclusion in lead-
    action details. Returns ``None`` (the explicit no-signal marker)
    when the projector never recorded a session for this agent — the
    lead playbook needs to distinguish "no gateway signal" from "fresh
    signal", so call sites add the ``gateway_session`` key
    unconditionally when ``gateway_session_by_agent_id`` was passed."""
    if task.assigned_agent_id is None:
        return None
    state = gateway_session_by_agent_id.get(task.assigned_agent_id)
    if state is None:
        return None
    return state.model_dump(include=_GATEWAY_SESSION_DETAIL_FIELDS)


def _in_progress_age_minutes(task: Task, *, now: datetime) -> int | None:
    age = _in_progress_age(task, now=now)
    if age is None:
        return None
    return max(0, int(age.total_seconds() // 60))


def _blocker_effective_age_at(
    blocker: OpenBlockerRow,
    *,
    lead_agent_id: UUID | None = None,
) -> datetime:
    """Return the timestamp the stale-blocker tier should age against.

    Acknowledgement is the owner's "I'm on it" signal — once recorded,
    the lead waits another grace window before re-nudging. The
    "fresher" of the two timestamps wins so the tier reflects
    whichever check-in is more recent. Pre-ack blockers age from
    creation. Codex review 2026-05-04 flagged that
    ``acknowledged_at OR created_at`` would mis-age a blocker if
    ``acknowledged_at < created_at`` (corrupted/replayed data); use
    ``max`` to be defensive. All datetimes coerced to naive UTC
    because PostgreSQL ``TIMESTAMP WITH TIME ZONE`` returns aware
    while ``utcnow()`` is naive.

    ``lead_agent_id``: when non-null AND
    ``blocker.acknowledged_by_agent_id`` matches it, the
    acknowledgement is treated as if absent (effective age =
    created_at). Lead self-ack on a worker-owned blocker is the
    production-gap pattern from 2026-05-04 — Supervisor self-acked
    parent blocker 64c0d937 and AC6 child f7529869 to silence the
    gate temporarily, but the gate re-fired on every grace cycle
    because the acker couldn't actually do the unblock work.
    Code-level enforcement complements the ``lead-health-scan``
    skill rule (cached prompts may miss the doc).
    """
    created = as_naive_utc(blocker.created_at)
    if blocker.acknowledged_at is None:
        return created
    if (
        lead_agent_id is not None
        and blocker.acknowledged_by_agent_id == lead_agent_id
    ):
        return created
    return max(created, as_naive_utc(blocker.acknowledged_at))


def select_lead_next_action(
    inputs: LeadInputs,
    *,
    now: datetime | None = None,
) -> LeadNextActionRead:
    """Return the single closest-to-done lead action from structured state.

    ``inputs.gateway_session_by_agent_id`` is the slice-4 projection of
    the OpenClaw gateway's per-session state, keyed by
    ``task.assigned_agent_id``. When provided,
    ``inspect_stale_in_progress`` actions include a ``gateway_session``
    field in details so the lead can distinguish "agent silent on the
    gateway" (likely wedged) from "agent active but task DB unmoved"
    (likely just slow). Optional — omitting it preserves the pre-slice-5
    details shape.
    """
    if now is None:
        now = utcnow()
    tasks_with_open_blocker = inputs.tasks_with_open_blocker or frozenset()
    tasks_with_pending_operator_decision = (
        inputs.tasks_with_pending_operator_decision or frozenset()
    )

    active_tasks = [
        task
        for task in inputs.tasks
        if task.status in {"inbox", "in_progress", "review", "rework"}
        and not _is_waiting(
            task,
            inputs.blocked_by_task_id,
            tasks_with_open_blocker,
            tasks_with_pending_operator_decision,
        )
    ]
    ordered = sorted(active_tasks, key=_task_sort_key)
    review_readiness_by_task_id = inputs.review_readiness_by_task_id or {}

    for task in ordered:
        if task.status != "review":
            continue
        if inputs.approval_state_by_task_id.get(task.id, "none") == "approved":
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
        approval_state = inputs.approval_state_by_task_id.get(task.id, "none")
        readiness = review_readiness_by_task_id.get(task.id)
        missing_pipeline = list(inputs.pipeline_missing_by_task_id.get(task.id, []))
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
        approval_state = inputs.approval_state_by_task_id.get(task.id, "none")
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
        missing_pipeline = list(inputs.pipeline_missing_by_task_id.get(task.id, []))
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
        if task.id not in inputs.pipeline_missing_by_task_id:
            continue
        missing_pipeline = list(inputs.pipeline_missing_by_task_id.get(task.id, []))
        if not missing_pipeline:
            details: dict[str, object] = {
                "review_packet_type": task.review_packet_type,
                "validation_target": task.validation_target,
                "pipeline_ready": True,
                "missing_pipeline_states": [],
                "missing_worker_pipeline_states": [],
                "missing_deploy_pipeline_states": [],
                "in_progress_minutes": _in_progress_age_minutes(task, now=now),
                "next_step": "nudge_assigned_worker_to_patch_status_review",
                "lead_may_not_patch_review": True,
            }
            if inputs.gateway_session_by_agent_id is not None:
                details["gateway_session"] = _gateway_session_details(
                    task, inputs.gateway_session_by_agent_id
                )
            return _action(
                task=task,
                action_required=True,
                action="inspect_stale_in_progress",
                reason_code="in_progress_worker_ready_for_review_submission",
                details=details,
            )
        if _in_progress_is_fresh(
            task,
            now=now,
            grace=IN_PROGRESS_PIPELINE_NUDGE_GRACE,
        ):
            continue
        owner_split = split_missing_states_by_default_owner(missing_pipeline)
        details = {
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
        }
        if inputs.gateway_session_by_agent_id is not None:
            details["gateway_session"] = _gateway_session_details(
                task, inputs.gateway_session_by_agent_id
            )
        return _action(
            task=task,
            action_required=True,
            action="inspect_stale_in_progress",
            reason_code="in_progress_pipeline_missing_review_gate",
            details=details,
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
    if inputs.orphan_children_with_terminal_parent:
        orphan_candidates = sorted(
            (
                task for task in inputs.tasks
                if task.id in inputs.orphan_children_with_terminal_parent
                and task.status not in TERMINAL_STATUSES
                and task.status not in {"review", "in_progress"}
            ),
            key=lambda t: str(t.id),
        )
        if orphan_candidates:
            orphan_task = orphan_candidates[0]
            parent_id = inputs.orphan_children_with_terminal_parent[orphan_task.id]
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

    # Inbox tasks already assigned to a reviewer/architect awaiting
    # Supervisor materialization. The ``lead-inbox-routing``
    # decomposition handshake is: (1) lead assigns task to Architect,
    # (2) Architect posts decomposition plan as a comment, (3) lead
    # reads plan and creates parent-linked subtasks, (4) lead retires
    # the umbrella with an ``UMBRELLA_RETIRED`` marker comment. Without
    # a tier here, step (3) never gets surfaced because the
    # ``route_inbox`` tier below requires ``assigned_agent_id IS
    # NULL``. Placed BEFORE ``route_inbox`` so an older Architect-
    # assigned task with a plan posted is processed before a fresh
    # unassigned arrival — otherwise a steady stream of fresh inbox
    # work could starve materialization indefinitely.
    #
    # Two idempotency signals: skip if children already exist via
    # ``parent_task_id`` (Phase V cascade) OR if an
    # ``UMBRELLA_RETIRED`` marker comment is present (covers
    # pre-Phase-V umbrellas where children predate ``parent_task_id``
    # and so don't show up in ``tasks_with_children``).
    tasks_with_children = inputs.tasks_with_children or frozenset()
    tasks_with_umbrella_retired_marker = (
        inputs.tasks_with_umbrella_retired_marker or frozenset()
    )
    for task in ordered:
        if task.status != "inbox" or task.assigned_agent_id is None:
            continue
        if task.id in tasks_with_children:
            continue
        if task.id in tasks_with_umbrella_retired_marker:
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

    # Phase V §I9 Fix 3 — surface stale blocked tasks to the lead.
    # ``_is_waiting()`` filters blocked tasks out of ``active_tasks``,
    # so without this tier the lead has no actionable signal for parked
    # work. AC5 incident at 2026-05-02 sat blocked + invisible for ~12h
    # because the gate's clear-fallback was the only path that
    # acknowledged blocked tasks (and that path is non-actionable).
    # Iterates the full ``tasks`` list (not ``ordered``) since blocked
    # tasks were filtered out earlier. Sorted by id for deterministic
    # cleanup ordering across calls. Fires only after
    # ``STALE_BLOCKER_NUDGE_GRACE`` so owners get time to act before
    # the lead nudges. Above ``route_inbox`` so a stuck blocked
    # closer-to-done task wins over fresh untriaged inbox arrivals.
    if inputs.open_blockers_by_task_id:
        # PostgreSQL ``TIMESTAMP WITH TIME ZONE`` columns return tz-aware
        # datetimes via asyncpg, while ``utcnow()`` is tz-naive (project
        # convention; see ``app.core.time``). Coerce blocker timestamps
        # to naive UTC before comparing so production deploys (PG, aware)
        # and local tests (SQLite, sometimes naive) both work without
        # raising ``TypeError: can't compare offset-naive and
        # offset-aware datetimes``. Production gap 2026-05-04 (req
        # 2f667e65): the stale-blocker tier 500'd here.
        #
        # ``_blocker_effective_age_at`` returns the freshness clock —
        # acknowledged_at when the owner explicitly claimed the work,
        # else created_at. Acknowledgement resets the stale clock so the
        # lead waits another grace window before re-nudging an owner
        # who has confirmed they're on it. If the owner goes silent
        # post-ack the tier still re-fires (defensively) once the new
        # window expires. Production gap 2026-05-04 (parent QA gate
        # blocker 64c0d937): Supervisor acknowledged the blocker but
        # the tier kept firing because ack was ignored, bursting the
        # comment endpoint past per-IP rate-limit (e0ce97132).
        stale_threshold = now - STALE_BLOCKER_NUDGE_GRACE
        stale_candidates = sorted(
            (
                task
                for task in inputs.tasks
                if task.status in {"inbox", "in_progress", "review", "rework"}
                and task.id in inputs.open_blockers_by_task_id
                and any(
                    _blocker_effective_age_at(
                        blocker, lead_agent_id=inputs.lead_agent_id,
                    ) < stale_threshold
                    for blocker in inputs.open_blockers_by_task_id.get(task.id, ())
                )
            ),
            key=lambda t: str(t.id),
        )
        if stale_candidates:
            stale_task = stale_candidates[0]
            blockers = list(inputs.open_blockers_by_task_id.get(stale_task.id, ()))
            oldest = min(
                blockers,
                key=lambda b: _blocker_effective_age_at(
                    b, lead_agent_id=inputs.lead_agent_id,
                ),
            )
            return _action(
                task=stale_task,
                action_required=True,
                action="inspect_stale_blocker",
                reason_code="stale_open_blocker_needs_owner_followup",
                details={
                    "blocker_count": len(blockers),
                    "blocker_ids": [str(b.id) for b in blockers],
                    "reason_codes": [
                        b.reason_code for b in blockers if b.reason_code is not None
                    ],
                    "owner_role": oldest.owner_role,
                    "acknowledged_by_agent_id": (
                        str(oldest.acknowledged_by_agent_id)
                        if oldest.acknowledged_by_agent_id is not None
                        else None
                    ),
                    "oldest_blocker_age_minutes": max(
                        0,
                        int((now - as_naive_utc(oldest.created_at)).total_seconds() // 60),
                    ),
                    "stale_blocker_grace_minutes": int(
                        STALE_BLOCKER_NUDGE_GRACE.total_seconds() // 60
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
        details = {
            "in_progress_minutes": _in_progress_age_minutes(task, now=now),
            "in_progress_grace_minutes": int(
                IN_PROGRESS_PIPELINE_NUDGE_GRACE.total_seconds() // 60
            ),
        }
        if inputs.gateway_session_by_agent_id is not None:
            details["gateway_session"] = _gateway_session_details(
                task, inputs.gateway_session_by_agent_id
            )
        return _action(
            task=task,
            action_required=True,
            action="inspect_stale_in_progress",
            reason_code="in_progress_work_needs_health_check",
            details=details,
        )

    # Classify the empty-queue ``clear`` so the Supervisor's drain loop
    # can distinguish "idle, no work" from "all work is waiting on
    # operator approval / structured blocker / fresh in_progress grace".
    # All four sub-states still return ``action_required=False``; only
    # the reason_code and details differ. Precedence is "most actionable
    # for the operator first" — pending approval surfaces above blocked
    # because the operator can resolve it directly.
    pending_approval_count = 0
    blocked_count = 0
    fresh_in_progress_count = 0
    active_state_count = 0
    for task in inputs.tasks:
        if task.status not in {"inbox", "in_progress", "review", "rework"}:
            continue
        active_state_count += 1
        if _is_waiting(
            task,
            inputs.blocked_by_task_id,
            tasks_with_open_blocker,
            tasks_with_pending_operator_decision,
        ):
            blocked_count += 1
            continue
        if (
            task.status == "review"
            and inputs.approval_state_by_task_id.get(task.id, "none") == "pending"
        ):
            pending_approval_count += 1
        elif task.status == "in_progress" and _in_progress_is_fresh(
            task,
            now=now,
            grace=IN_PROGRESS_PIPELINE_NUDGE_GRACE,
        ):
            fresh_in_progress_count += 1

    other_active_count = (
        active_state_count
        - pending_approval_count
        - blocked_count
        - fresh_in_progress_count
    )
    clear_details: dict[str, object] = {
        "active_state_count": active_state_count,
        "pending_approval_count": pending_approval_count,
        "blocked_count": blocked_count,
        "fresh_in_progress_count": fresh_in_progress_count,
        "other_active_count": other_active_count,
    }
    if active_state_count == 0:
        clear_reason = "no_active_work"
    elif pending_approval_count == active_state_count:
        clear_reason = "only_pending_approval"
    elif blocked_count == active_state_count:
        clear_reason = "only_blocked"
    elif fresh_in_progress_count == active_state_count:
        clear_reason = "only_fresh_in_progress"
    else:
        clear_reason = "only_waiting_or_no_active_work"

    return _action(
        task=None,
        action_required=False,
        action="clear",
        reason_code=clear_reason,
        details=clear_details,
    )
