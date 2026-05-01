"""Task pipeline event helpers and review readiness gates."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc
from sqlmodel import col, select

from app.models.task_pipeline_events import TaskPipelineEvent
from app.schemas.task_pipeline_events import INFORMATIONAL_PIPELINE_STATES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.tasks import Task

FRONTEND_PIPELINE_PACKET_TYPES = frozenset({"frontend_ui", "mixed"})
FRONTEND_REVIEW_PIPELINE_STATES = (
    "code_changed",
    "committed",
    "built",
    "deployed",
    "live_build_verified",
    "runtime_verified",
)
PIPELINE_REQUIRED_FIELDS_BY_STATE = {
    "committed": ("commit_sha",),
    "built": ("commit_sha", "artifact_hash"),
    "deployed": ("artifact_hash", "deploy_target"),
    "live_build_verified": ("deploy_target", "live_sha"),
    "runtime_verified": ("deploy_target", "evidence"),
}
# Default role-owner per state in the typical OpenClaw board topology
# (DevOps owns build/deploy; the implementation worker owns code/runtime checks).
# Boards that assign deploy ownership to the implementation worker should treat
# both sets as worker-owned at the skill layer.
PIPELINE_STATE_DEFAULT_OWNER = {
    "code_changed": "worker",
    "committed": "worker",
    "built": "deploy",
    "deployed": "deploy",
    "live_build_verified": "worker",
    "runtime_verified": "worker",
}


def frontend_pipeline_required(review_packet_type: str | None) -> bool:
    return review_packet_type in FRONTEND_PIPELINE_PACKET_TYPES


class PipelineOwnerSplit(NamedTuple):
    """Pipeline states grouped by default role-owner."""

    worker: list[str]
    deploy: list[str]


def split_missing_states_by_default_owner(
    missing: Sequence[str],
) -> PipelineOwnerSplit:
    """Group missing pipeline states by default role-owner."""
    worker: list[str] = []
    deploy: list[str] = []
    for state in missing:
        if PIPELINE_STATE_DEFAULT_OWNER.get(state) == "deploy":
            deploy.append(state)
        else:
            worker.append(state)
    return PipelineOwnerSplit(worker=worker, deploy=deploy)


async def list_task_pipeline_events(
    session: AsyncSession,
    *,
    task_id: UUID,
    since: datetime | None = None,
) -> list[TaskPipelineEvent]:
    statement = select(TaskPipelineEvent).where(col(TaskPipelineEvent.task_id) == task_id)
    if since is not None:
        statement = statement.where(col(TaskPipelineEvent.created_at) >= since)
    statement = statement.order_by(desc(col(TaskPipelineEvent.created_at)))
    return list(await session.exec(statement))


async def list_task_pipeline_events_for_tasks(
    session: AsyncSession,
    *,
    task_ids: Sequence[UUID],
) -> dict[UUID, list[TaskPipelineEvent]]:
    """Batch-fetch pipeline events grouped by task_id (one SQL pass).

    Per-task ``cycle_since`` filtering is the caller's job — each task has
    its own cycle. Events within a group are sorted ``created_at DESC``.
    """
    if not task_ids:
        return {}
    statement = (
        select(TaskPipelineEvent)
        .where(col(TaskPipelineEvent.task_id).in_(list(task_ids)))
        .order_by(desc(col(TaskPipelineEvent.created_at)))
    )
    events_by_task: dict[UUID, list[TaskPipelineEvent]] = {}
    for event in await session.exec(statement):
        events_by_task.setdefault(event.task_id, []).append(event)
    return events_by_task


def pipeline_present_states(events: Sequence[TaskPipelineEvent]) -> list[str]:
    """Distinct readiness-relevant states observed in the event stream.

    Informational states (``INFORMATIONAL_PIPELINE_STATES``) are excluded
    so they never affect ``ready`` calculations or appear next to true
    readiness milestones. Use ``latest_model_fallback_step`` for trajectory
    visibility.
    """
    present: list[str] = []
    seen: set[str] = set()
    for event in sorted(events, key=lambda value: value.created_at):
        if event.state in INFORMATIONAL_PIPELINE_STATES:
            continue
        if not pipeline_event_has_required_fields(event):
            continue
        if event.state in seen:
            continue
        seen.add(event.state)
        present.append(event.state)
    return present


def latest_model_fallback_step(
    events: Sequence[TaskPipelineEvent],
) -> TaskPipelineEvent | None:
    """Return the most recent ``model_fallback`` event from a pre-fetched list.

    Used by callers that ALREADY have the full event list in memory
    (e.g., the pipeline-state endpoint at /tasks/{id}/pipeline). For
    callers that only need the latest fallback step, prefer
    :func:`fetch_latest_model_fallback_step` — it pushes the filter to
    SQL with ``LIMIT 1`` instead of round-tripping every event.
    """
    fallbacks = [event for event in events if event.state == "model_fallback"]
    if not fallbacks:
        return None
    return max(fallbacks, key=lambda value: value.created_at)


async def fetch_latest_model_fallback_step(
    session: AsyncSession,
    *,
    task_id: UUID,
    since: datetime | None = None,
) -> TaskPipelineEvent | None:
    """SQL-side fetch of the most recent ``model_fallback`` event for one task.

    Use this for the per-task API endpoint (``/tasks/{id}/review-readiness``).
    For multi-task callers (lead next-action loop), use
    :func:`fetch_latest_model_fallback_steps_for_tasks` instead — calling
    this in a loop is an N+1.
    """
    statement = (
        select(TaskPipelineEvent)
        .where(col(TaskPipelineEvent.task_id) == task_id)
        .where(col(TaskPipelineEvent.state) == "model_fallback")
    )
    if since is not None:
        statement = statement.where(col(TaskPipelineEvent.created_at) >= since)
    statement = statement.order_by(desc(col(TaskPipelineEvent.created_at))).limit(1)
    rows = list(await session.exec(statement))
    return rows[0] if rows else None


async def fetch_latest_model_fallback_steps_for_tasks(
    session: AsyncSession,
    *,
    task_ids: Sequence[UUID],
) -> dict[UUID, TaskPipelineEvent]:
    """Batch-fetch the latest ``model_fallback`` event per task in one query.

    Per-task ``cycle_since`` filtering is the caller's job — each task has
    its own cycle, so SQL-level since filtering would need a shared lower
    bound. The query orders by ``task_id, created_at DESC``; the first row
    seen per ``task_id`` is the latest.
    """
    if not task_ids:
        return {}
    statement = (
        select(TaskPipelineEvent)
        .where(col(TaskPipelineEvent.task_id).in_(list(task_ids)))
        .where(col(TaskPipelineEvent.state) == "model_fallback")
        .order_by(col(TaskPipelineEvent.task_id), desc(col(TaskPipelineEvent.created_at)))
    )
    latest_by_task: dict[UUID, TaskPipelineEvent] = {}
    for event in await session.exec(statement):
        if event.task_id not in latest_by_task:
            latest_by_task[event.task_id] = event
    return latest_by_task


def pipeline_event_has_required_fields(event: TaskPipelineEvent) -> bool:
    return not pipeline_missing_required_fields(
        state=event.state,
        values={
            "commit_sha": event.commit_sha,
            "artifact_hash": event.artifact_hash,
            "deploy_target": event.deploy_target,
            "live_sha": event.live_sha,
            "evidence": event.evidence,
        },
    )


def pipeline_missing_required_fields(
    *,
    state: str,
    values: dict[str, object | None],
) -> list[str]:
    required_fields = PIPELINE_REQUIRED_FIELDS_BY_STATE.get(state, ())
    missing: list[str] = []
    for field_name in required_fields:
        value = values.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field_name)
            continue
        if isinstance(value, dict) and not value:
            missing.append(field_name)
    return missing


def pipeline_missing_states(
    events: Sequence[TaskPipelineEvent],
    *,
    required_states: Sequence[str] = FRONTEND_REVIEW_PIPELINE_STATES,
) -> list[str]:
    present = set(pipeline_present_states(events))
    return [state for state in required_states if state not in present]


def _pipeline_incomplete_error(
    *,
    task: Task,
    present_states: Sequence[str],
    missing_states: Sequence[str],
    since: datetime | None,
) -> HTTPException:
    first_missing = missing_states[0]
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                f"Structured pipeline is at `{present_states[-1] if present_states else 'start'}` "
                f"state; missing `{first_missing}` before review routing."
            ),
            "code": "task_pipeline_incomplete",
            "remediation": (
                "Record structured evidence with "
                "POST /api/v1/boards/{board_id}/tasks/{task_id}/pipeline/events "
                f"for `{first_missing}` and every later missing state, then retry review."
            ),
            "task_id": str(task.id),
            "packet_type": task.review_packet_type,
            "required_states": list(FRONTEND_REVIEW_PIPELINE_STATES),
            "present_states": list(present_states),
            "missing_states": list(missing_states),
            "first_missing_state": first_missing,
            "since": since.isoformat() if since is not None else None,
        },
    )


async def require_frontend_pipeline_ready_for_review(
    session: AsyncSession,
    *,
    task: Task,
    since: datetime | None,
) -> None:
    if not frontend_pipeline_required(task.review_packet_type):
        return
    events = await list_task_pipeline_events(session, task_id=task.id, since=since)
    present_states = pipeline_present_states(events)
    missing_states = pipeline_missing_states(events)
    if missing_states:
        raise _pipeline_incomplete_error(
            task=task,
            present_states=present_states,
            missing_states=missing_states,
            since=since,
        )
