"""Generic Redis-backed queue helpers for RQ-backed background workloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


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


def enqueue_task(task: QueuedTask, queue_name: str, *, redis_url: str | None = None) -> bool:
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


def dequeue_task(queue_name: str, *, redis_url: str | None = None) -> QueuedTask | None:
    """Pop one task envelope from the queue."""
    client = _redis_client(redis_url=redis_url)
    raw = cast(str | bytes | None, client.rpop(queue_name))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        payload: dict[str, Any] = json.loads(raw)
        if "task_type" not in payload and "payload" not in payload:
            return QueuedTask(
                task_type="legacy",
                payload=payload,
                created_at=_coerce_datetime(payload.get("created_at") or payload.get("received_at")),
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
) -> bool:
    """Requeue a failed task with capped retries.

    Returns True if requeued.
    """
    if task.attempts >= max_retries:
        logger.warning(
            "rq.queue.drop_failed_task",
            extra={
                "task_type": task.task_type,
                "queue_name": queue_name,
                "attempts": task.attempts,
            },
        )
        return False
    return enqueue_task(_requeue_with_attempt(task), queue_name, redis_url=redis_url)
