"""Structured review verdict helpers and readiness gates."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import desc
from sqlmodel import col, select

from app.models.tasks import Task
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.task_review_events import TaskReviewEvent
from app.schemas.task_pipeline_events import TaskPipelineEventRead
from app.schemas.task_review_events import TaskReviewEventRead, TaskReviewReadinessRead

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


def _cycle_since(task: "Task") -> datetime | None:
    return task.in_progress_at or task.previous_in_progress_at


def _latest_events_by_role(
    *,
    task: "Task",
    events: Sequence[TaskReviewEvent],
) -> dict[str, TaskReviewEvent]:
    since = _cycle_since(task)
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


def _coerce_uuid_list(value: object) -> list[UUID] | None:
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

    declared_child_task_ids = _coerce_uuid_list(evidence.get("planned_child_task_ids"))
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
    latest_by_role = _latest_events_by_role(task=task, events=events)
    present_roles = [role for role in required_roles if role in latest_by_role]
    missing_roles = [role for role in required_roles if role not in latest_by_role]
    blocking_roles = [
        role
        for role in required_roles
        if latest_by_role.get(role) is not None
        and latest_by_role[role].verdict in BLOCKING_VERDICTS
    ]
    artifact_issues, declared_child_task_ids, missing_child_task_ids = (
        _review_only_artifact_state(
            task=task,
            latest_by_role=latest_by_role,
            board_task_ids=board_task_ids,
        )
    )
    ready = bool(required_roles) and not missing_roles and not blocking_roles and all(
        latest_by_role[role].verdict == PASS_VERDICT for role in required_roles
    ) and not artifact_issues
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


async def get_task_review_readiness(
    session: "AsyncSession",
    *,
    task: "Task",
) -> TaskReviewReadinessRead:
    """Load structured review verdicts and compute readiness for a task."""

    events = await list_task_review_events(session, task_id=task.id)
    board_task_ids: set[UUID] | None = None
    if task.board_id is not None:
        board_task_ids = set(
            await session.exec(select(Task.id).where(col(Task.board_id) == task.board_id)),
        )

    # Pull the latest model_fallback pipeline event for the current cycle.
    # Pushes ``state = 'model_fallback'`` + ``ORDER BY created_at DESC
    # LIMIT 1`` to SQL so the per-task cost is one targeted row, not a
    # full event-list fetch (avoids the N+1 pattern when the lead loops
    # every review task on next-action).
    from app.services.task_pipeline import fetch_latest_model_fallback_step

    cycle_since = task.in_progress_at or task.previous_in_progress_at
    latest_fallback = await fetch_latest_model_fallback_step(
        session,
        task_id=task.id,
        since=cycle_since,
    )

    return build_review_readiness(
        task=task,
        events=events,
        board_task_ids=board_task_ids,
        latest_fallback_step=latest_fallback,
    )
