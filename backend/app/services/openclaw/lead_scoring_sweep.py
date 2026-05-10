"""Phase VI §I5 lead heartbeat no-op scoring sweeper.

Runs on its own loop (5-min default) rather than piggybacking the
existing heartbeat_sweep so the two cadences stay independent —
Phase 0 heartbeat repair runs every 60s; lead scoring at 60s cadence
would over-count on legitimate quiet intervals.

Each tick opens a session, calls ``score_all_leads_once``, logs the
candidate-emit count, and waits for the next interval. The stop
event is driven by the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.services.lead_scoring import score_all_leads_once

logger = get_logger(__name__)


async def lead_scoring_sweep_loop(stop_event: asyncio.Event) -> None:
    interval_seconds = settings.lead_scoring_sweep_interval_seconds
    sweep_interval = timedelta(seconds=interval_seconds)
    logger.info(
        "lead_scoring_sweep.loop_started interval_seconds=%s",
        interval_seconds,
    )
    try:
        while not stop_event.is_set():
            try:
                async with async_session_maker() as session:
                    emitted = await score_all_leads_once(session, sweep_interval=sweep_interval)
                if emitted:
                    logger.info(
                        "lead_scoring_sweep.candidates_emitted count=%s",
                        emitted,
                    )
            except Exception:
                logger.exception("lead_scoring_sweep.iteration_failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        logger.info("lead_scoring_sweep.loop_stopped")


async def stop_lead_scoring_sweep(
    task: asyncio.Task[None] | None, stop_event: asyncio.Event
) -> None:
    stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
