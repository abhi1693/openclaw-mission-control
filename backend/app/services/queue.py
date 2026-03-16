"""Generic Redis-backed queue helpers for RQ-backed background workloads."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_SCHEDULED_SUFFIX = ":scheduled"
_DRY_RUN_BATCH_SIZE = 100


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


def _redis_client(redis_url: str | None = None) -> redis.Redis:
    return redis.Redis.from_url(redis_url or settings.rq_redis_url)


def _scheduled_queue_name(queue_name: str) -> str:
    return f"{queue_name}{_SCHEDULED_SUFFIX}"


def _now_seconds() -> float:
    return time.time()


def _drain_ready_scheduled_tasks(
    client: redis.Redis,
    queue_name: str,
    *,
    max_items: int = _DRY_RUN_BATCH_SIZE,
) -> float | None:
    scheduled_queue = _scheduled_queue_name(queue_name)
    now = _now_seconds()

    ready_items = cast(
        list[str | bytes],
        client.zrangebyscore(
            scheduled_queue,
            "-inf",
            now,
            start=0,
            num=max_items,
        ),
    )
    if ready_items:
        ready_values = tuple(ready_items)
        client.lpush(queue_name, *ready_values)
        client.zrem(scheduled_queue, *ready_values)
        logger.debug(
            "rq.queue.drain_ready_scheduled",
            extra={
                "queue_name": queue_name,
                "count": len(ready_items),
            },
        )

    next_item = cast(
        list[tuple[str | bytes, float]],
        client.zrangebyscore(
            scheduled_queue,
            now,
            "+inf",
            start=0,
            num=1,
            withscores=True,
        ),
    )
    if not next_item:
        return None

    next_score = float(next_item[0][1])
    return max(0.0, next_score - now)


def _schedule_for_later(
    task: QueuedTask,
    queue_name: str,
    delay_seconds: float,
    *,
    redis_url: str | None = None,
) -> bool:
    client = _redis_client(redis_url=redis_url)
    scheduled_queue = _scheduled_queue_name(queue_name)
    score = _now_seconds() + delay_seconds
    client.zadd(scheduled_queue, {task.to_json(): score})
    logger.info(
        "rq.queue.scheduled",
        extra={
            "task_type": task.task_type,
            "queue_name": queue_name,
            "delay_seconds": delay_seconds,
        },
    )
    return True


def enqueue_task(
    task: QueuedTask,
    queue_name: str,
    *,
    redis_url: str | None = None,
) -> bool:
    """Persist a task envelope in a Redis list-backed queue."""
    try:
        client = _redis_client(redis_url=redis_url)
        client.lpush(queue_name, task.to_json())
        logger.info(
            "rq.queue.enqueued",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "attempt": task.attempts,
            },
        )
        return True
    except Exception as exc:
        logger.warning(
            "rq.queue.enqueue_failed",
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
    """Enqueue a task immediately or schedule it for delayed delivery."""
    delay = max(0.0, float(delay_seconds))
    if delay == 0:
        return enqueue_task(task, queue_name, redis_url=redis_url)
    try:
        return _schedule_for_later(task, queue_name, delay, redis_url=redis_url)
    except Exception as exc:
        logger.warning(
            "rq.queue.schedule_failed",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "delay_seconds": delay,
                "error": str(exc),
            },
        )
        return False


def _coerce_datetime(raw: object | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(UTC)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=UTC)
        except (TypeError, ValueError, OverflowError):
            return datetime.now(UTC)
    return datetime.now(UTC)


def dequeue_task(
    queue_name: str,
    *,
    redis_url: str | None = None,
    block: bool = False,
    block_timeout: float = 0,
) -> QueuedTask | None:
    """Pop one task envelope from the queue."""
    client = _redis_client(redis_url=redis_url)
    timeout = max(0.0, float(block_timeout))
    raw: str | bytes | None
    if block:
        next_delay = _drain_ready_scheduled_tasks(client, queue_name)
        if timeout == 0:
            timeout = next_delay if next_delay is not None else 0
        else:
            timeout = min(timeout, next_delay) if next_delay is not None else timeout
        raw_result = cast(
            tuple[bytes | str, bytes | str] | None,
            client.brpop([queue_name], timeout=timeout),
        )
        if raw_result is None:
            _drain_ready_scheduled_tasks(client, queue_name)
            return None
        raw = raw_result[1]
    else:
        raw = cast(str | bytes | None, client.rpop(queue_name))
    if raw is None:
        _drain_ready_scheduled_tasks(client, queue_name)
        return None
    return _decode_task(raw, queue_name)


def _decode_task(raw: str | bytes, queue_name: str) -> QueuedTask:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        payload: dict[str, Any] = json.loads(raw)
        if "task_type" not in payload and "payload" not in payload:
            return QueuedTask(
                task_type="legacy",
                payload=payload,
                created_at=_coerce_datetime(
                    payload.get("created_at") or payload.get("received_at")
                ),
                attempts=int(payload.get("attempts", 0)),
            )
        return QueuedTask(
            task_type=str(payload["task_type"]),
            payload=payload["payload"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            attempts=int(payload.get("attempts", 0)),
        )
    except Exception as exc:
        logger.error(
            "rq.queue.dequeue_failed",
            extra={"queue_name": queue_name, "raw_payload": str(raw), "error": str(exc)},
        )
        raise


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
    """Requeue a failed task with capped retries.

    Returns True if requeued.
    """
    requeued_task = _requeue_with_attempt(task)
    if requeued_task.attempts > max_retries:
        logger.warning(
            "rq.queue.drop_failed_task",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "attempts": requeued_task.attempts,
            },
        )
        return False
    if delay_seconds > 0:
        return _schedule_for_later(
            requeued_task,
            queue_name,
            delay_seconds,
            redis_url=redis_url,
        )
    return enqueue_task(
        requeued_task,
        queue_name,
        redis_url=redis_url,
    )
