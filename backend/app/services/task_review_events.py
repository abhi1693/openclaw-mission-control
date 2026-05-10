"""Structured review verdict helpers and readiness gates."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import desc
from sqlmodel import col, select

from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.task_review_events import TaskReviewEvent
from app.models.tasks import Task
from app.schemas.task_pipeline_events import TaskPipelineEventRead
from app.schemas.task_review_events import TaskReviewEventRead, TaskReviewReadinessRead
from app.services.task_pipeline import (
    fetch_latest_model_fallback_step,
    fetch_latest_model_fallback_steps_for_tasks,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

PASS_VERDICT = "pass"
BLOCKING_VERDICTS = frozenset({"fail", "inconclusive", "infra_blocked"})
REQUIRED_REVIEW_ROLES_BY_PACKET_TYPE = {
    "frontend_ui": ("architect", "qa_e2e"),
    "backend_api": ("architect", "qa_unit"),
    "infra_ops": ("devops",),
    "mixed": ("architect", "qa_unit", "qa_e2e", "devops"),
    "review_only": ("architect",),
    "content_copy": ("architect",),
}


def required_review_roles(review_packet_type: str | None) -> list[str]:
    """Return structured verdict roles required for the task packet type."""

    return list(REQUIRED_REVIEW_ROLES_BY_PACKET_TYPE.get(review_packet_type or "", ()))


def cycle_since(task: "Task") -> datetime | None:
    return task.in_progress_at or task.previous_in_progress_at


def latest_events_by_role(
    *,
    task: "Task",
    events: Sequence[TaskReviewEvent],
) -> dict[str, TaskReviewEvent]:
    since = cycle_since(task)
    latest: dict[str, TaskReviewEvent] = {}
    for event in sorted(events, key=lambda value: value.created_at):
        if since is not None and event.created_at < since:
            continue
        latest[event.reviewer_role] = event
    return latest


def task_review_event_read(event: TaskReviewEvent) -> TaskReviewEventRead:
    """Serialize a structured review verdict event."""

    return TaskReviewEventRead(
        id=event.id,
        board_id=event.board_id,
        task_id=event.task_id,
        agent_id=event.agent_id,
        reviewer_role=event.reviewer_role,
        verdict=event.verdict,
        evidence_type=event.evidence_type,
        target=event.target,
        build_hash=event.build_hash,
        source_commit=event.source_commit,
        blocking_owner=event.blocking_owner,
        suggested_routing=event.suggested_routing,
        evidence=event.evidence,
        created_at=event.created_at,
    )


def coerce_uuid_list(value: object) -> list[UUID] | None:
    """Coerce a JSON evidence value to a list of UUIDs.

    Returns ``None`` if the value is not a list, contains non-string
    non-UUID items, or contains strings that don't parse as UUIDs.
    Empty input list returns ``[]`` (caller decides whether empty is
    acceptable). Used by both the read-side review-readiness gate and
    the write-side ``/review-events`` POST guard so both layers reject
    the same malformed payloads.
    """
    if not isinstance(value, list):
        return None
    parsed: list[UUID] = []
    for item in value:
        if isinstance(item, UUID):
            parsed.append(item)
            continue
        if not isinstance(item, str):
            return None
        try:
            parsed.append(UUID(item))
        except ValueError:
            return None
    return parsed


def _is_present_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_pass_value(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == PASS_VERDICT


def _is_zero_count(value: object) -> bool:
    return type(value) is int and value == 0


def _non_empty_dict_rows(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, list) or not value:
        return None
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        rows.append(item)
    return rows


def qa_e2e_pass_evidence_issues(
    *,
    evidence_type: str | None,
    target: str | None,
    build_hash: str | None,
    evidence: object,
) -> list[str]:
    """Return the list of QA-E2E PASS evidence issues for a given
    record's fields. Pure — operates on the same field shape exposed
    by both ``TaskReviewEvent`` (read-side) and
    ``TaskReviewEventCreate`` (write-side) so the two paths share one
    rule set.
    """
    issues: list[str] = []
    if evidence_type != "browser":
        issues.append("qa_e2e_pass_wrong_evidence_type")
    if not _is_present_text(target):
        issues.append("qa_e2e_pass_missing_target")
    if not _is_present_text(build_hash):
        issues.append("qa_e2e_pass_missing_build_hash")

    evidence_dict = evidence if isinstance(evidence, dict) else {}
    ac_rows = _non_empty_dict_rows(evidence_dict.get("ac_rows"))
    if ac_rows is None:
        issues.append("qa_e2e_pass_missing_ac_rows")
    elif any(not _is_pass_value(row.get("result")) for row in ac_rows):
        issues.append("qa_e2e_pass_ac_rows_have_failures")

    browser_matrix = _non_empty_dict_rows(evidence_dict.get("browser_matrix"))
    if browser_matrix is None:
        issues.append("qa_e2e_pass_missing_browser_matrix")
    elif any(
        not _is_pass_value(row.get("result"))
        or not _is_zero_count(row.get("console_errors"))
        or not _is_zero_count(row.get("network_failures"))
        or not _is_present_text(row.get("route"))
        or not _is_present_text(row.get("viewport"))
        for row in browser_matrix
    ):
        issues.append("qa_e2e_pass_browser_matrix_has_failures")

    return issues


def _qa_e2e_pass_artifact_issues(
    *,
    latest_by_role: dict[str, TaskReviewEvent],
    required_roles: Sequence[str],
) -> list[str]:
    if "qa_e2e" not in required_roles:
        return []

    event = latest_by_role.get("qa_e2e")
    if event is None or event.verdict != PASS_VERDICT:
        return []

    return qa_e2e_pass_evidence_issues(
        evidence_type=event.evidence_type,
        target=event.target,
        build_hash=event.build_hash,
        evidence=event.evidence,
    )


def _review_only_artifact_state(
    *,
    task: Task,
    latest_by_role: dict[str, TaskReviewEvent],
    board_task_ids: Collection[UUID] | None,
) -> tuple[list[str], list[UUID], list[UUID]]:
    if task.review_packet_type != "review_only":
        return [], [], []

    architect_event = latest_by_role.get("architect")
    if architect_event is None or architect_event.verdict != PASS_VERDICT:
        return [], [], []

    evidence = architect_event.evidence or {}
    if not isinstance(evidence, dict):
        return ["review_only_architect_pass_missing_child_task_evidence"], [], []

    if evidence.get("no_child_tasks_required") is True:
        return [], [], []

    declared_child_task_ids = coerce_uuid_list(evidence.get("planned_child_task_ids"))
    if not declared_child_task_ids:
        return ["review_only_architect_pass_missing_child_task_evidence"], [], []

    if task.id in declared_child_task_ids:
        return (
            ["review_only_architect_pass_includes_parent_task_id"],
            declared_child_task_ids,
            [],
        )

    if board_task_ids is None:
        return [], declared_child_task_ids, []

    missing_child_task_ids = [
        task_id for task_id in declared_child_task_ids if task_id not in board_task_ids
    ]
    if missing_child_task_ids:
        return (
            ["review_only_architect_pass_child_tasks_not_found"],
            declared_child_task_ids,
            missing_child_task_ids,
        )

    return [], declared_child_task_ids, []


def build_review_readiness(
    *,
    task: Task,
    events: Sequence[TaskReviewEvent],
    board_task_ids: Collection[UUID] | None = None,
    latest_fallback_step: TaskPipelineEvent | None = None,
) -> TaskReviewReadinessRead:
    """Compute whether structured reviewer verdicts satisfy current task gates.

    The optional ``latest_fallback_step`` is informational — it is surfaced
    inline so reviewers see WHICH model produced the packet, but it does
    NOT participate in readiness gating.
    """

    required_roles = required_review_roles(task.review_packet_type)
    latest_by_role = latest_events_by_role(task=task, events=events)
    present_roles = [role for role in required_roles if role in latest_by_role]
    missing_roles = [role for role in required_roles if role not in latest_by_role]
    blocking_roles = [
        role
        for role in required_roles
        if latest_by_role.get(role) is not None
        and latest_by_role[role].verdict in BLOCKING_VERDICTS
    ]
    artifact_issues = _qa_e2e_pass_artifact_issues(
        latest_by_role=latest_by_role,
        required_roles=required_roles,
    )
    review_only_artifact_issues, declared_child_task_ids, missing_child_task_ids = (
        _review_only_artifact_state(
            task=task,
            latest_by_role=latest_by_role,
            board_task_ids=board_task_ids,
        )
    )
    artifact_issues.extend(review_only_artifact_issues)
    ready = (
        bool(required_roles)
        and not missing_roles
        and not blocking_roles
        and all(latest_by_role[role].verdict == PASS_VERDICT for role in required_roles)
        and not artifact_issues
    )
    fallback_payload: TaskPipelineEventRead | None = None
    if latest_fallback_step is not None:
        fallback_payload = TaskPipelineEventRead.model_validate(
            latest_fallback_step,
            from_attributes=True,
        )
    return TaskReviewReadinessRead(
        task_id=task.id,
        review_packet_type=task.review_packet_type,
        required_roles=required_roles,
        present_roles=present_roles,
        missing_roles=missing_roles,
        blocking_roles=blocking_roles,
        artifact_issues=artifact_issues,
        declared_child_task_ids=declared_child_task_ids,
        missing_child_task_ids=missing_child_task_ids,
        ready=ready,
        events=[
            task_review_event_read(event)
            for event in sorted(events, key=lambda value: value.created_at, reverse=True)
        ],
        latest_fallback_step=fallback_payload,
    )


async def list_task_review_events(
    session: "AsyncSession",
    *,
    task_id: UUID,
    since: datetime | None = None,
) -> list[TaskReviewEvent]:
    """Return structured review verdicts for a task."""

    statement = select(TaskReviewEvent).where(col(TaskReviewEvent.task_id) == task_id)
    if since is not None:
        statement = statement.where(col(TaskReviewEvent.created_at) >= since)
    statement = statement.order_by(desc(col(TaskReviewEvent.created_at)))
    return list(await session.exec(statement))


async def list_task_review_events_for_tasks(
    session: "AsyncSession",
    *,
    task_ids: Sequence[UUID],
) -> dict[UUID, list[TaskReviewEvent]]:
    """Batch-fetch review events grouped by task_id (one SQL pass).

    Per-task ``cycle_since`` filtering is the caller's job — each task has
    its own cycle. Events within a group are sorted ``created_at DESC``.
    """
    if not task_ids:
        return {}
    statement = (
        select(TaskReviewEvent)
        .where(col(TaskReviewEvent.task_id).in_(list(task_ids)))
        .order_by(desc(col(TaskReviewEvent.created_at)))
    )
    events_by_task: dict[UUID, list[TaskReviewEvent]] = {}
    for event in await session.exec(statement):
        events_by_task.setdefault(event.task_id, []).append(event)
    return events_by_task


async def get_task_review_readiness(
    session: "AsyncSession",
    *,
    task: "Task",
) -> TaskReviewReadinessRead:
    """Load structured review verdicts and compute readiness for a task."""

    since = cycle_since(task)
    events = await list_task_review_events(session, task_id=task.id, since=since)
    board_task_ids: set[UUID] | None = None
    if task.board_id is not None:
        board_task_ids = set(
            await session.exec(select(Task.id).where(col(Task.board_id) == task.board_id)),
        )

    latest_fallback = await fetch_latest_model_fallback_step(
        session,
        task_id=task.id,
        since=since,
    )

    return build_review_readiness(
        task=task,
        events=events,
        board_task_ids=board_task_ids,
        latest_fallback_step=latest_fallback,
    )


async def get_task_review_readiness_batch(
    session: "AsyncSession",
    *,
    tasks: Sequence["Task"],
) -> dict[UUID, TaskReviewReadinessRead]:
    """Batched readiness computation for multiple tasks.

    For the lead next-action loop. Issues: 1 query per distinct board for
    ``board_task_ids``, 1 query for all review events, 1 query for all
    fallback steps. Replaces the per-task ``get_task_review_readiness``
    pattern (3 queries × N tasks).

    Per-task ``cycle_since`` filtering is applied in Python after the
    batch fetches, since each task has its own cycle.
    """
    if not tasks:
        return {}

    distinct_board_ids = {task.board_id for task in tasks if task.board_id is not None}
    board_task_ids_by_board: dict[UUID, set[UUID]] = {}
    for board_id in distinct_board_ids:
        board_task_ids_by_board[board_id] = set(
            await session.exec(select(Task.id).where(col(Task.board_id) == board_id)),
        )

    task_ids = [task.id for task in tasks]
    events_by_task = await list_task_review_events_for_tasks(session, task_ids=task_ids)
    fallback_by_task = await fetch_latest_model_fallback_steps_for_tasks(session, task_ids=task_ids)

    out: dict[UUID, TaskReviewReadinessRead] = {}
    for task in tasks:
        since = cycle_since(task)
        events = events_by_task.get(task.id, [])
        if since is not None:
            events = [event for event in events if event.created_at >= since]

        latest_fallback = fallback_by_task.get(task.id)
        if latest_fallback is not None and since is not None and latest_fallback.created_at < since:
            latest_fallback = None

        board_task_ids = (
            board_task_ids_by_board.get(task.board_id) if task.board_id is not None else None
        )

        out[task.id] = build_review_readiness(
            task=task,
            events=events,
            board_task_ids=board_task_ids,
            latest_fallback_step=latest_fallback,
        )
    return out
