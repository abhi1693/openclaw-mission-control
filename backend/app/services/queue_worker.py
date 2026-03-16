"""Generic queue worker with task-type dispatch."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger
from app.services.openclaw.lifecycle_queue import TASK_TYPE as LIFECYCLE_RECONCILE_TASK_TYPE
from app.services.openclaw.lifecycle_queue import (
    requeue_lifecycle_queue_task,
)
from app.services.openclaw.lifecycle_reconcile import process_lifecycle_queue_task
from app.services.queue import QueuedTask, dequeue_task
from app.services.webhooks.dispatch import (
    process_webhook_queue_task,
    requeue_webhook_queue_task,
)
from app.services.webhooks.queue import TASK_TYPE as WEBHOOK_TASK_TYPE

logger = get_logger(__name__)
_WORKER_BLOCK_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class _TaskHandler:
    handler: Callable[[QueuedTask], Awaitable[None]]
    attempts_to_delay: Callable[[int], float]
    requeue: Callable[[QueuedTask, float], bool]


_TASK_HANDLERS: dict[str, _TaskHandler] = {
    LIFECYCLE_RECONCILE_TASK_TYPE: _TaskHandler(
        handler=process_lifecycle_queue_task,
        attempts_to_delay=lambda attempts: min(
            settings.rq_dispatch_retry_base_seconds * (2 ** max(0, attempts)),
            settings.rq_dispatch_retry_max_seconds,
        ),
        requeue=lambda task, delay: requeue_lifecycle_queue_task(task, delay_seconds=delay),
    ),
    WEBHOOK_TASK_TYPE: _TaskHandler(
        handler=process_webhook_queue_task,
        attempts_to_delay=lambda attempts: min(
            settings.rq_dispatch_retry_base_seconds * (2 ** max(0, attempts)),
            settings.rq_dispatch_retry_max_seconds,
        ),
        requeue=lambda task, delay: requeue_webhook_queue_task(task, delay_seconds=delay),
    ),
}


def _compute_jitter(base_delay: float) -> float:
    return random.uniform(0, min(settings.rq_dispatch_retry_max_seconds / 10, base_delay * 0.1))


async def flush_queue(*, block: bool = False, block_timeout: float = 0) -> int:
    """Consume one queue batch and dispatch by task type."""
    processed = 0
    while True:
        try:
            task = dequeue_task(
                settings.rq_queue_name,
                redis_url=settings.rq_redis_url,
                block=block,
                block_timeout=block_timeout,
            )
        except Exception:
            logger.exception(
                "queue.worker.dequeue_failed",
                extra={"queue_name": settings.rq_queue_name},
            )
            continue

        if task is None:
            break

        handler = _TASK_HANDLERS.get(task.task_type)
        if handler is None:
            logger.warning(
                "queue.worker.task_unhandled",
                extra={
                    "task_type": task.task_type,
                    "queue_name": settings.rq_queue_name,
                },
            )
            continue

        try:
            await handler.handler(task)
            processed += 1
            logger.info(
                "queue.worker.success",
                extra={
                    "task_type": task.task_type,
                    "attempt": task.attempts,
                },
            )
        except Exception as exc:
            logger.exception(
                "queue.worker.failed",
                extra={
                    "task_type": task.task_type,
                    "attempt": task.attempts,
                    "error": str(exc),
                },
            )
            base_delay = handler.attempts_to_delay(task.attempts)
            delay = base_delay + _compute_jitter(base_delay)
            if not handler.requeue(task, delay):
                logger.warning(
                    "queue.worker.drop_task",
                    extra={
                        "task_type": task.task_type,
                        "attempt": task.attempts,
                    },
                )
        await asyncio.sleep(settings.rq_dispatch_throttle_seconds)

    if processed > 0:
        logger.info("queue.worker.batch_complete", extra={"count": processed})
    return processed


async def _run_worker_loop() -> None:
    while True:
        try:
            await flush_queue(
                block=True,
                # Keep a finite timeout so scheduled tasks are periodically drained.
                block_timeout=_WORKER_BLOCK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception(
                "queue.worker.loop_failed",
                extra={"queue_name": settings.rq_queue_name},
            )
            await asyncio.sleep(1)


def run_worker() -> None:
    """RQ entrypoint for running continuous queue processing."""
    logger.info(
        "queue.worker.batch_started",
        extra={"throttle_seconds": settings.rq_dispatch_throttle_seconds},
    )
    try:
        asyncio.run(_run_worker_loop())
    finally:
        logger.info("queue.worker.stopped", extra={"queue_name": settings.rq_queue_name})
