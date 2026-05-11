"""Async deploy parity check — Phase 2 of pipeline-transition-gates.

After a task transitions to ``review``, a background job fetches the
live validation target's ``/__build`` SHA and compares it against the
task's ``packet_commit_sha``.  If they mismatch, the job reverts the
task to ``in_progress`` and auto-posts a diagnostic comment.

Uses compare-and-swap guards so stale jobs cannot revert newer
submissions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.services.deploy_truth import (
    DeployTruthFetchError,
    fetch_build_metadata,
    packet_sha_matches_live,
)
from app.services.queue import QueuedTask, enqueue_task

logger = get_logger(__name__)

TASK_TYPE = "deploy_parity_check"
_QUEUE_NAME_DEFAULT = "mc:queue:default"


def enqueue_deploy_parity_check(
    *,
    task_id: UUID,
    board_id: UUID,
    packet_commit_sha: str,
    validation_target: str,
    expected_updated_at: str,
    prior_agent_id: UUID | None,
) -> bool:
    """Enqueue a deploy parity check after a review transition.

    Call this AFTER the DB commit so the worker reads committed state.
    """

    payload: dict[str, Any] = {
        "task_id": str(task_id),
        "board_id": str(board_id),
        "packet_commit_sha": packet_commit_sha,
        "validation_target": validation_target,
        "expected_updated_at": expected_updated_at,
        "prior_agent_id": str(prior_agent_id) if prior_agent_id else None,
    }
    queued = QueuedTask(
        task_type=TASK_TYPE,
        payload=payload,
        created_at=datetime.now(UTC),
    )
    return enqueue_task(
        queued,
        settings.rq_queue_name or _QUEUE_NAME_DEFAULT,
        redis_url=settings.rq_redis_url,
    )


def requeue_deploy_parity_task(task: QueuedTask, delay_seconds: float) -> bool:
    """Requeue a failed deploy parity check with delay."""

    from app.services.queue import enqueue_task_with_delay

    return enqueue_task_with_delay(
        task,
        settings.rq_queue_name or _QUEUE_NAME_DEFAULT,
        delay_seconds=delay_seconds,
        redis_url=settings.rq_redis_url,
    )


async def process_deploy_parity_task(task: QueuedTask) -> None:
    """Background handler: fetch live /__build and compare.

    On mismatch: revert task to in_progress + auto-post comment.
    On match: no action.
    On fetch error: log + requeue (transient).
    """

    payload = task.payload
    task_id = UUID(payload["task_id"])
    board_id = UUID(payload["board_id"])
    packet_sha = payload["packet_commit_sha"]
    target = payload["validation_target"]
    expected_updated_at = payload["expected_updated_at"]
    prior_agent_id_str = payload.get("prior_agent_id")
    prior_agent_id = UUID(prior_agent_id_str) if prior_agent_id_str else None

    logger.info(
        "deploy_parity.check_start",
        extra={
            "task_id": str(task_id),
            "packet_sha": packet_sha,
            "target": target,
        },
    )

    # Fetch live /__build
    try:
        metadata = await fetch_build_metadata(target)
    except DeployTruthFetchError as exc:
        logger.warning(
            "deploy_parity.fetch_failed",
            extra={
                "task_id": str(task_id),
                "target": target,
                "error": str(exc),
            },
        )
        # Transient — will be requeued by the worker retry logic
        raise

    live_sha = metadata.sha
    if live_sha is None:
        logger.info(
            "deploy_parity.no_live_sha",
            extra={"task_id": str(task_id), "target": target},
        )
        # Target doesn't report a SHA — degraded, no enforcement
        return

    if packet_sha_matches_live(packet_sha=packet_sha, live_sha=live_sha):
        logger.info(
            "deploy_parity.match",
            extra={
                "task_id": str(task_id),
                "packet_sha": packet_sha,
                "live_sha": live_sha,
            },
        )
        return

    # MISMATCH — revert to in_progress with CAS guard
    logger.warning(
        "deploy_parity.mismatch",
        extra={
            "task_id": str(task_id),
            "packet_sha": packet_sha,
            "live_sha": live_sha,
        },
    )

    await _revert_to_in_progress(
        task_id=task_id,
        board_id=board_id,
        packet_sha=packet_sha,
        live_sha=live_sha,
        target=target,
        expected_updated_at=expected_updated_at,
        prior_agent_id=prior_agent_id,
    )


async def _revert_to_in_progress(
    *,
    task_id: UUID,
    board_id: UUID,
    packet_sha: str,
    live_sha: str,
    target: str,
    expected_updated_at: str,
    prior_agent_id: UUID | None,
) -> None:
    """Atomic compare-and-swap revert: only revert if task state matches.

    Uses ``UPDATE ... WHERE`` so the guard check and mutation are one
    atomic SQL statement — no TOCTOU race.
    """

    from sqlalchemy import text

    from app.db.session import async_session_maker

    message = (
        f"Deploy parity failed: live `{target}/__build` reports SHA "
        f"`{live_sha}`, but `packet_commit_sha` is `{packet_sha}`. "
        f"The deployed build does not match your commit. "
        f"Build and deploy before resubmitting to review.\n\n"
        f"Task reverted to `in_progress` automatically."
    )

    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC to match DB

    async with async_session_maker() as session:
        # Atomic CAS: UPDATE only if all guards match
        result = await session.exec(  # type: ignore[call-overload]
            text("""
                UPDATE tasks
                SET status = 'in_progress',
                    assigned_agent_id = :prior_agent_id,
                    in_progress_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                  AND status = 'review'
                  AND packet_commit_sha = :packet_sha
                  AND updated_at = :expected_updated_at
            """),
            params={
                "task_id": str(task_id),
                "prior_agent_id": str(prior_agent_id) if prior_agent_id else None,
                "now": now,
                "packet_sha": packet_sha,
                "expected_updated_at": expected_updated_at,
            },
        )

        rows_affected = result.rowcount

        if rows_affected == 0:
            logger.info(
                "deploy_parity.revert_skipped",
                extra={
                    "task_id": str(task_id),
                    "reason": "cas_guard_failed",
                },
            )
            await session.rollback()
            return

        # Post diagnostic comment in same transaction
        from app.models.activity_events import ActivityEvent

        comment = ActivityEvent(
            event_type="task.comment",
            task_id=task_id,
            message=message,
            agent_id=None,  # system comment
        )
        session.add(comment)
        await session.commit()

        logger.info(
            "deploy_parity.reverted",
            extra={
                "task_id": str(task_id),
                "prior_agent_id": str(prior_agent_id) if prior_agent_id else None,
                "rows_affected": rows_affected,
            },
        )
