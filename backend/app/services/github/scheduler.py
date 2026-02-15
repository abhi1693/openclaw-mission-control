"""Scheduler bootstrap for Mission Control GitHub approval check reconciliation.

This uses rq-scheduler (same pattern as webhook dispatch scheduler) to periodically
reconcile the `mission-control/approval` check run state.

The periodic job is a safety net; primary updates happen on:
- approval create / resolution
- task github_pr_url updates
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from redis import Redis
from rq_scheduler import Scheduler  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.logging import get_logger
from app.services.github.worker import run_reconcile_mission_control_approval_checks

logger = get_logger(__name__)


def bootstrap_mission_control_approval_check_schedule(
    interval_seconds: int | None = None,
    *,
    max_attempts: int = 5,
    retry_sleep_seconds: float = 1.0,
) -> None:
    """Register a recurring reconciliation job for GitHub approval checks."""

    effective_interval_seconds = (
        settings.github_approval_check_schedule_interval_seconds
        if interval_seconds is None
        else interval_seconds
    )

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            connection = Redis.from_url(settings.webhook_redis_url)
            connection.ping()
            scheduler = Scheduler(
                queue_name=settings.webhook_queue_name,
                connection=connection,
            )

            for job in scheduler.get_jobs():
                if job.id == settings.github_approval_check_schedule_id:
                    scheduler.cancel(job)

            scheduler.schedule(
                datetime.now(tz=timezone.utc) + timedelta(seconds=10),
                func=run_reconcile_mission_control_approval_checks,
                interval=effective_interval_seconds,
                repeat=None,
                id=settings.github_approval_check_schedule_id,
                queue_name=settings.webhook_queue_name,
            )
            logger.info(
                "github.approval_check.scheduler.bootstrapped",
                extra={
                    "schedule_id": settings.github_approval_check_schedule_id,
                    "queue_name": settings.webhook_queue_name,
                    "interval_seconds": effective_interval_seconds,
                },
            )
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "github.approval_check.scheduler.bootstrap_failed",
                extra={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "error": str(exc),
                },
            )
            if attempt < max_attempts:
                time.sleep(retry_sleep_seconds * attempt)

    raise RuntimeError("Failed to bootstrap GitHub approval check schedule") from last_exc
