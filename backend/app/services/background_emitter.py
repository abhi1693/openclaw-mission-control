"""Shared fire-and-forget background-task emitter.

Pulls the bounded-strong-ref pattern used by the Phase 0 shadow-metric
emit out of ``api/tasks.py`` so new signals (Phase V deploy-truth
degraded, Phase VI lane-quieting ticks, etc.) can reuse it instead of
hand-rolling the same 128-slot backlog + task set + done-callback +
drain routine.

Usage:

    _emitter = BackgroundEmitter(name="my_signal", max_pending=128)

    def schedule_my_signal(...) -> None:
        _emitter.schedule(my_emit_coroutine(...), log_key=str(task_id))

    async def lifespan_shutdown() -> None:
        await _emitter.drain()

Each emitter holds strong references to pending tasks so asyncio
doesn't garbage-collect them mid-flight (which would produce "Task
was destroyed but it is pending" warnings). Completed tasks are
auto-discarded via a done callback. The ``max_pending`` cap drops
new signals rather than piling up unbounded under a slow-DB storm.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class BackgroundEmitter:
    """Bounded background-task runner with drain-on-shutdown support."""

    def __init__(self, *, name: str, max_pending: int = 128) -> None:
        self._name = name
        self._max_pending = max_pending
        self._pending: set[asyncio.Task[None]] = set()

    def schedule(self, coro: Coroutine[Any, Any, None], *, log_key: str) -> bool:
        """Schedule ``coro`` to run in the background.

        ``log_key`` is any string identifier (task id, board id, etc.)
        that will appear in the "backlog full, dropped" WARN line if
        the emitter is at capacity.

        Returns True when the coroutine is actually queued on the
        event loop; returns False when the backlog was full and the
        coroutine was closed (so the caller can suppress any dedupe
        bookkeeping tied to the emit).
        """

        if len(self._pending) >= self._max_pending:
            logger.warning(
                "background_emitter.dropped_backlog_full "
                "emitter=%s pending=%d limit=%d log_key=%s",
                self._name,
                len(self._pending),
                self._max_pending,
                log_key,
            )
            # Close the already-constructed coroutine so asyncio
            # doesn't later emit "coroutine was never awaited".
            coro.close()
            return False
        task = asyncio.create_task(coro, name=f"background_emitter.{self._name}")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return True

    async def drain(self) -> None:
        """Wait for any in-flight tasks to complete.

        Called from the FastAPI lifespan shutdown path so pending
        background writes finish (or explicitly cancel + log) before
        the event loop tears down.
        """

        pending = list(self._pending)
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
