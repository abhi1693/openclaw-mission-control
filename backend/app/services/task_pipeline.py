"""Task pipeline event helpers and review readiness gates."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc
from sqlmodel import col, select

from app.models.task_pipeline_events import TaskPipelineEvent

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


def frontend_pipeline_required(review_packet_type: str | None) -> bool:
    return review_packet_type in FRONTEND_PIPELINE_PACKET_TYPES


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


def pipeline_present_states(events: Sequence[TaskPipelineEvent]) -> list[str]:
    present: list[str] = []
    seen: set[str] = set()
    for event in sorted(events, key=lambda value: value.created_at):
        if event.state in seen:
            continue
        seen.add(event.state)
        present.append(event.state)
    return present


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
