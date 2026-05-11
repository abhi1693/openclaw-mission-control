"""Phase 0 retention purge for append-only observability tables.

Implements amendment §A.4: rows in ``shadow_metric_events`` older than
``settings.shadow_metric_retention_days`` (default 90) are deleted daily.
Also purges ``agent_heartbeat_repair_events`` under the same cutoff, as
that migration's header docstring already anticipated.

Both tables carry created_at indexes, so the range delete is cheap even
at multi-million-row scale.

Pattern mirrors ``heartbeat_watchdog_loop`` in app/services/openclaw —
lifespan starts one background task, shutdown cancels it and awaits
cleanly.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.shadow_metric_events import ShadowMetricEvent

logger = get_logger(__name__)

# Daily cadence. More frequent would be wasted reads against the
# created_at index; less frequent lets the tables grow beyond the
# operator's expectation.
RETENTION_PURGE_INTERVAL_SECONDS = 24 * 60 * 60


async def _purge_table(
    session: AsyncSession,
    *,
    model: type,
    retention_days: int,
) -> int:
    """Delete rows of ``model`` created more than ``retention_days`` ago.

    Returns the number of rows deleted.
    """

    threshold = utcnow() - timedelta(days=retention_days)
    # ``model`` is a SQLModel subclass with a ``created_at`` column;
    # the abstract ``type`` parameter doesn't expose it statically.
    created_at_col = cast(Any, model).created_at
    statement = delete(model).where(col(created_at_col) < threshold)
    result = await session.exec(statement)
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_shadow_metric_events_once(session: AsyncSession, *, retention_days: int) -> int:
    """Delete shadow_metric_events rows older than ``retention_days`` days."""

    return await _purge_table(session, model=ShadowMetricEvent, retention_days=retention_days)


async def purge_heartbeat_repair_events_once(session: AsyncSession, *, retention_days: int) -> int:
    """Delete agent_heartbeat_repair_events rows older than ``retention_days``."""

    return await _purge_table(
        session, model=AgentHeartbeatRepairEvent, retention_days=retention_days
    )


async def run_retention_purge_once(retention_days: int) -> dict[str, int]:
    """One full retention sweep across both observability tables.

    Opens a fresh session, purges both tables, commits once. Returns a
    per-table row-count summary for logging.
    """

    async with async_session_maker() as session:
        shadow_deleted = await purge_shadow_metric_events_once(
            session, retention_days=retention_days
        )
        heartbeat_deleted = await purge_heartbeat_repair_events_once(
            session, retention_days=retention_days
        )
        await session.commit()
    return {
        "shadow_metric_events": shadow_deleted,
        "agent_heartbeat_repair_events": heartbeat_deleted,
    }


async def retention_purge_loop(stop_event: asyncio.Event, *, retention_days: int) -> None:
    """Long-running task: daily purge until stopped.

    Runs the sweep immediately on startup (so a freshly-restarted worker
    doesn't wait a full day to catch up on retention), then sleeps.
    """

    logger.info(
        "retention_purge.loop_started interval_seconds=%s retention_days=%d",
        RETENTION_PURGE_INTERVAL_SECONDS,
        retention_days,
    )
    try:
        while not stop_event.is_set():
            try:
                summary = await run_retention_purge_once(retention_days=retention_days)
                logger.info(
                    "retention_purge.complete shadow_deleted=%d heartbeat_deleted=%d",
                    summary["shadow_metric_events"],
                    summary["agent_heartbeat_repair_events"],
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("retention_purge.iteration_failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=RETENTION_PURGE_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue
    finally:
        logger.info("retention_purge.loop_stopped")


async def stop_retention_purge(task: asyncio.Task[None] | None, stop_event: asyncio.Event) -> None:
    """Graceful shutdown for the retention purge loop."""

    stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
