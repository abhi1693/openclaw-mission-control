"""In-process async queue for background workloads (replaces Redis/RQ)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# In-memory task queue (single-process, no persistence)
_task_queue: asyncio.Queue[QueuedTask] | None = None
_delayed_tasks: list[tuple[float, QueuedTask]] = []


@dataclass(frozen=True)
class QueuedTask:
    """Generic queued task envelope."""

    task_type: str
    payload: dict[str, Any]
    created_at: datetime
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "task_type": self.task_type,
                "payload": self.payload,
                "created_at": self.created_at.isoformat(),
                "attempts": self.attempts,
            },
            sort_keys=True,
        )


def _get_queue() -> asyncio.Queue[QueuedTask]:
    global _task_queue
    if _task_queue is None:
        _task_queue = asyncio.Queue()
    return _task_queue


def enqueue_task(
    task: QueuedTask,
    queue_name: str,
    *,
    redis_url: str | None = None,
) -> bool:
    """Add a task to the in-memory queue."""
    try:
        _get_queue().put_nowait(task)
        logger.info(
            "queue.enqueued",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "attempt": task.attempts,
            },
        )
        return True
    except Exception as exc:
        logger.warning(
            "queue.enqueue_failed",
            extra={"task_type": task.task_type, "queue_name": queue_name, "error": str(exc)},
        )
        return False


def enqueue_task_with_delay(
    task: QueuedTask,
    queue_name: str,
    *,
    delay_seconds: float,
    redis_url: str | None = None,
) -> bool:
    """Enqueue a task with optional delay (delay executed via asyncio.create_task)."""
    delay = max(0.0, float(delay_seconds))
    if delay == 0:
        return enqueue_task(task, queue_name)

    async def _delayed_enqueue() -> None:
        await asyncio.sleep(delay)
        enqueue_task(task, queue_name)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_delayed_enqueue())
        logger.info(
            "queue.scheduled",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "delay_seconds": delay,
            },
        )
        return True
    except RuntimeError:
        # No running event loop — just enqueue immediately
        return enqueue_task(task, queue_name)


def dequeue_task(
    queue_name: str,
    *,
    redis_url: str | None = None,
    block: bool = False,
    block_timeout: float = 0,
) -> QueuedTask | None:
    """Pop one task from the in-memory queue (non-blocking)."""
    try:
        return _get_queue().get_nowait()
    except asyncio.QueueEmpty:
        return None


def _requeue_with_attempt(task: QueuedTask) -> QueuedTask:
    return QueuedTask(
        task_type=task.task_type,
        payload=task.payload,
        created_at=task.created_at,
        attempts=task.attempts + 1,
    )


def requeue_if_failed(
    task: QueuedTask,
    queue_name: str,
    *,
    max_retries: int,
    redis_url: str | None = None,
    delay_seconds: float = 0,
) -> bool:
    """Requeue a failed task with capped retries."""
    requeued_task = _requeue_with_attempt(task)
    if requeued_task.attempts > max_retries:
        logger.warning(
            "queue.drop_failed_task",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "attempts": requeued_task.attempts,
            },
        )
        return False
    if delay_seconds > 0:
        return enqueue_task_with_delay(
            requeued_task, queue_name, delay_seconds=delay_seconds
        )
    return enqueue_task(requeued_task, queue_name)
