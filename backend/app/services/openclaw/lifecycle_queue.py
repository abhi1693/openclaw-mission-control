"""Queue payload helpers for stuck-agent lifecycle reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.queue import QueuedTask, enqueue_task_with_delay
from app.services.queue import requeue_if_failed as generic_requeue_if_failed

logger = get_logger(__name__)
TASK_TYPE = "agent_lifecycle_reconcile"


@dataclass(frozen=True)
class QueuedAgentLifecycleReconcile:
    """Queued payload metadata for lifecycle reconciliation checks."""

    agent_id: UUID
    gateway_id: UUID
    board_id: UUID | None
    generation: int
    checkin_deadline_at: datetime
    attempts: int = 0


def _task_from_payload(payload: QueuedAgentLifecycleReconcile) -> QueuedTask:
    return QueuedTask(
        task_type=TASK_TYPE,
        payload={
            "agent_id": str(payload.agent_id),
            "gateway_id": str(payload.gateway_id),
            "board_id": str(payload.board_id) if payload.board_id is not None else None,
            "generation": payload.generation,
            "checkin_deadline_at": payload.checkin_deadline_at.isoformat(),
        },
        created_at=utcnow(),
        attempts=payload.attempts,
    )


def decode_lifecycle_task(task: QueuedTask) -> QueuedAgentLifecycleReconcile:
    if task.task_type not in {TASK_TYPE, "legacy"}:
        raise ValueError(f"Unexpected task_type={task.task_type!r}; expected {TASK_TYPE!r}")
    payload: dict[str, Any] = task.payload
    raw_board_id = payload.get("board_id")
    board_id = UUID(raw_board_id) if isinstance(raw_board_id, str) and raw_board_id else None
    raw_deadline = payload.get("checkin_deadline_at")
    if not isinstance(raw_deadline, str):
        raise ValueError("checkin_deadline_at is required")
    return QueuedAgentLifecycleReconcile(
        agent_id=UUID(str(payload["agent_id"])),
        gateway_id=UUID(str(payload["gateway_id"])),
        board_id=board_id,
        generation=int(payload["generation"]),
        checkin_deadline_at=datetime.fromisoformat(raw_deadline),
        attempts=int(payload.get("attempts", task.attempts)),
    )


def enqueue_lifecycle_reconcile(payload: QueuedAgentLifecycleReconcile) -> bool:
    """Enqueue a delayed reconcile check keyed to the expected check-in deadline."""
    now = utcnow()
    delay_seconds = max(0.0, (payload.checkin_deadline_at - now).total_seconds())
    queued = _task_from_payload(payload)
    ok = enqueue_task_with_delay(
        queued,
        settings.rq_queue_name,
        delay_seconds=delay_seconds,
        redis_url=settings.rq_redis_url,
    )
    if ok:
        logger.info(
            "lifecycle.queue.enqueued",
            extra={
                "agent_id": str(payload.agent_id),
                "generation": payload.generation,
                "delay_seconds": delay_seconds,
                "attempt": payload.attempts,
            },
        )
    return ok


def defer_lifecycle_reconcile(
    task: QueuedTask,
    *,
    delay_seconds: float,
) -> bool:
    """Defer a reconcile task without incrementing retry attempts."""
    payload = decode_lifecycle_task(task)
    deferred = QueuedAgentLifecycleReconcile(
        agent_id=payload.agent_id,
        gateway_id=payload.gateway_id,
        board_id=payload.board_id,
        generation=payload.generation,
        checkin_deadline_at=payload.checkin_deadline_at,
        attempts=task.attempts,
    )
    queued = _task_from_payload(deferred)
    return enqueue_task_with_delay(
        queued,
        settings.rq_queue_name,
        delay_seconds=max(0.0, delay_seconds),
        redis_url=settings.rq_redis_url,
    )


def requeue_lifecycle_queue_task(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    """Requeue a failed lifecycle task with capped retries."""
    return generic_requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )
