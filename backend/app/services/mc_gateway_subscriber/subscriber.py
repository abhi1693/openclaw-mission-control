"""WebSocket subscriber: connect, dispatch events to handlers, reconnect on drop.

Designed to run as a long-lived asyncio task inside a dedicated
``mc-gateway-subscriber`` worker process (see Decision 1 in the kickoff
design doc). Handlers are registered with ``.on(event_type, fn)`` and
called with the parsed JSON payload of each matching message.

Failure model:
- Handler exceptions are logged and the loop continues.
- WS connection drops trigger reconnect with exponential backoff
  (capped). Backoff resets on each successful connection.
- Caller signals shutdown by setting an ``asyncio.Event``; the
  subscriber closes its WS and returns from ``run()`` cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class Subscriber:
    """Persistent WebSocket consumer for gateway events.

    Args:
        url: ``ws://`` or ``wss://`` URL of the gateway WS endpoint.
        token: bearer token sent as ``Authorization: Bearer <token>``.
        reconnect_initial_delay: first backoff duration in seconds.
        reconnect_max_delay: cap on backoff duration in seconds.
    """

    def __init__(
        self,
        *,
        url: str,
        token: str,
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        self._url = url
        self._token = token
        self._initial_delay = reconnect_initial_delay
        self._max_delay = reconnect_max_delay
        self._handlers: dict[str, EventHandler] = {}

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register an async handler for messages whose ``type`` field matches."""
        self._handlers[event_type] = handler

    async def run(self, stop: asyncio.Event) -> None:
        """Connect, listen, dispatch, reconnect — until ``stop`` is set."""
        delay = self._initial_delay
        while not stop.is_set():
            try:
                async with websockets.connect(
                    self._url,
                    additional_headers={"Authorization": f"Bearer {self._token}"},
                ) as ws:
                    delay = self._initial_delay
                    await self._listen(ws, stop)
            except ConnectionClosed:
                logger.info("gateway WS connection closed; will reconnect")
            except Exception:
                logger.exception("gateway WS connect failed; will retry")
            if stop.is_set():
                return
            await self._sleep_with_stop(delay, stop)
            delay = min(delay * 2, self._max_delay)

    async def _listen(self, ws: Any, stop: asyncio.Event) -> None:
        """Read messages until the WS closes or ``stop`` is set."""
        recv_task = asyncio.create_task(self._recv_loop(ws))
        stop_task = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait(
                {recv_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                await ws.close()
        finally:
            for t in (recv_task, stop_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

    async def _recv_loop(self, ws: Any) -> None:
        async for raw in ws:
            await self._dispatch(raw)

    async def _dispatch(self, raw: Any) -> None:
        text = raw if isinstance(raw, str) else raw.decode(errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("dropping non-JSON message: %s", text[:200])
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return
        handler = self._handlers.get(event_type)
        if handler is None:
            return
        try:
            await handler(payload)
        except Exception:
            logger.exception("handler for %s raised; continuing", event_type)

    async def _sleep_with_stop(self, seconds: float, stop: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
