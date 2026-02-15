"""Webhook queue persistence and delivery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.services.queue import QueuedTask, dequeue_task, enqueue_task, requeue_if_failed as generic_requeue_if_failed

logger = get_logger(__name__)
TASK_TYPE = "webhook_delivery"


@dataclass(frozen=True)
class QueuedInboundDelivery:
    """Payload metadata stored for deferred webhook lead dispatch."""

    board_id: UUID
    webhook_id: UUID
    payload_id: UUID
    received_at: datetime
    attempts: int = 0


def _task_from_payload(payload: QueuedInboundDelivery) -> QueuedTask:
    return QueuedTask(
        task_type=TASK_TYPE,
        payload={
            "board_id": str(payload.board_id),
            "webhook_id": str(payload.webhook_id),
            "payload_id": str(payload.payload_id),
            "received_at": payload.received_at.isoformat(),
        },
        created_at=payload.received_at,
        attempts=payload.attempts,
    )


def _payload_from_task(task: QueuedTask) -> QueuedInboundDelivery:
    if task.task_type not in {TASK_TYPE, "legacy"}:
        raise ValueError(f"Unexpected task_type={task.task_type!r}; expected {TASK_TYPE!r}")

    payload: dict[str, Any] = task.payload
    if task.task_type == "legacy":
        received_at = payload.get("received_at") or payload.get("created_at")
        return QueuedInboundDelivery(
            board_id=UUID(payload["board_id"]),
            webhook_id=UUID(payload["webhook_id"]),
            payload_id=UUID(payload["payload_id"]),
            received_at=datetime.fromisoformat(received_at) if isinstance(received_at, str) else datetime.now(UTC),
            attempts=int(payload.get("attempts", task.attempts)),
        )

    return QueuedInboundDelivery(
        board_id=UUID(payload["board_id"]),
        webhook_id=UUID(payload["webhook_id"]),
        payload_id=UUID(payload["payload_id"]),
        received_at=datetime.fromisoformat(payload["received_at"]),
        attempts=int(payload.get("attempts", task.attempts)),
    )


def enqueue_webhook_delivery(payload: QueuedInboundDelivery) -> bool:
    """Persist webhook metadata in a Redis queue for batch dispatch."""
    try:
        queued = _task_from_payload(payload)
        enqueue_task(queued, settings.rq_queue_name, redis_url=settings.rq_redis_url)
        logger.info(
            "webhook.queue.enqueued",
            extra={
                "board_id": str(payload.board_id),
                "webhook_id": str(payload.webhook_id),
                "payload_id": str(payload.payload_id),
                "attempt": payload.attempts,
            },
        )
        return True
    except Exception as exc:
        logger.warning(
            "webhook.queue.enqueue_failed",
            extra={
                "board_id": str(payload.board_id),
                "webhook_id": str(payload.webhook_id),
                "payload_id": str(payload.payload_id),
                "error": str(exc),
            },
        )
        return False


def dequeue_webhook_delivery() -> QueuedInboundDelivery | None:
    """Pop one queued webhook delivery payload."""
    try:
        task = dequeue_task(settings.rq_queue_name, redis_url=settings.rq_redis_url)
        if task is None:
            return None
        return _payload_from_task(task)
    except Exception as exc:
        logger.error(
            "webhook.queue.dequeue_failed",
            extra={
                "queue_name": settings.rq_queue_name,
                "error": str(exc),
            },
        )
        raise


def requeue_if_failed(payload: QueuedInboundDelivery) -> bool:
    """Requeue payload delivery with capped retries.

    Returns True if requeued.
    """
    try:
        return generic_requeue_if_failed(
            _task_from_payload(payload),
            settings.rq_queue_name,
            max_retries=settings.rq_dispatch_max_retries,
            redis_url=settings.rq_redis_url,
        )
    except Exception as exc:
        logger.warning(
            "webhook.queue.requeue_failed",
            extra={
                "board_id": str(payload.board_id),
                "webhook_id": str(payload.webhook_id),
                "payload_id": str(payload.payload_id),
                "error": str(exc),
            },
        )
        raise
