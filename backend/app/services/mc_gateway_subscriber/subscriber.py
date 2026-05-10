"""WebSocket subscriber for OpenClaw gateway events.

Implements the gateway connect handshake observed in
``app/services/openclaw/gateway_rpc.py`` (frame shapes: ``req``,
``res``, ``event``; first message from the gateway is
``connect.challenge`` with a nonce). After the handshake, sends each
configured subscription as its own ``req`` and then loops on incoming
``event`` messages, dispatching to handlers registered with
``.on(event_name, fn)``.

Designed to run as a long-lived asyncio task inside a dedicated
``mc-gateway-subscriber`` worker process.

Failure model:
- Handler exceptions are logged and the loop continues.
- WS connection drops trigger reconnect with exponential backoff
  (capped). Backoff resets only after a connection has been alive long
  enough to be considered healthy — guards against post-handshake
  immediate-close storms (e.g. bad token, role mismatch).
- Caller signals shutdown by setting an ``asyncio.Event``; the
  subscriber closes its WS and returns from ``run()`` cleanly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import uuid4

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.logging import get_logger
from app.services.openclaw.protocol_constants import (
    PROTOCOL_VERSION,
    build_control_ui_connect_params,
    build_control_ui_origin,
)

logger = get_logger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]

# OpenClaw gateway protocol frame types and well-known event/method
# names. Defined here as constants so a typo in a string literal
# anywhere in this module surfaces at import time, not at runtime.
FRAME_TYPE_REQ = "req"
FRAME_TYPE_RES = "res"
FRAME_TYPE_EVENT = "event"
EVENT_CONNECT_CHALLENGE = "connect.challenge"
METHOD_CONNECT = "connect"

# Per-connection healthy signal: at least one event delivered AFTER
# the handshake. Connection uptime alone is misleading — a silent
# gateway that times out the handshake at the same threshold would
# look "healthy" by uptime and reset backoff (codex post-cleanup
# review, 2026-05-03).
_HANDSHAKE_TIMEOUT_SECONDS = 5.0
_CONNECT_RES_TIMEOUT_SECONDS = 5.0


class Subscriber:
    """Persistent WebSocket consumer for OpenClaw gateway events.

    Args:
        url: ``ws://`` or ``wss://`` URL of the gateway WS endpoint.
        token: bearer token sent as ``Authorization: Bearer <token>``
            on the WS handshake AND embedded in the ``connect`` req's
            ``params.auth.token`` field.
        subscriptions: ordered list of subscription RPC method names
            (e.g. ``"sessions.subscribe"``) to send after the
            handshake.
        reconnect_initial_delay: first backoff duration in seconds.
        reconnect_max_delay: cap on backoff duration in seconds.
        protocol_version: min/max protocol version sent in connect.
            Defaults to the upstream constant from
            ``protocol_constants``.

    Connect mode is fixed at ``control_ui`` (no device-pairing
    crypto). The gateway accepts that mode via the ``CONTROL_UI``
    client identity + ``Origin`` header — which means pairing-disabled
    operator workflows. If we ever need device-pairing mode, that's a
    separate code path.
    """

    def __init__(
        self,
        *,
        url: str,
        token: str,
        subscriptions: Sequence[str] = (),
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        protocol_version: int = PROTOCOL_VERSION,
    ) -> None:
        self._url = url
        self._token = token
        self._subscriptions = tuple(subscriptions)
        self._initial_delay = reconnect_initial_delay
        self._max_delay = reconnect_max_delay
        self._protocol_version = protocol_version
        self._handlers: dict[str, EventHandler] = {}
        # Per-connection state used by run() to decide whether the
        # connection was healthy enough to reset backoff. Reset to 0
        # at the start of each connect attempt; incremented in
        # _dispatch when an event is successfully delivered to a
        # handler (or matches a registered handler — even no-op
        # match counts).
        self._events_dispatched_this_connection = 0
        # Per-instance handshake timeout knob. Production default is
        # `_HANDSHAKE_TIMEOUT_SECONDS`; tests override to keep the
        # silent-gateway scenario fast.
        self._handshake_timeout_seconds = _HANDSHAKE_TIMEOUT_SECONDS

    def on(self, event_name: str, handler: EventHandler) -> None:
        """Register an async handler for events whose ``event`` field matches."""
        self._handlers[event_name] = handler

    async def run(self, stop: asyncio.Event) -> None:
        """Connect, handshake, subscribe, listen, dispatch — until ``stop``."""
        delay = self._initial_delay
        connect_kwargs: dict[str, Any] = {
            "additional_headers": {"Authorization": f"Bearer {self._token}"},
        }
        # Control-UI mode requires an Origin header matching the gateway
        # host. The gateway rejects connect frames from clients without
        # one when ``disable_device_pairing`` is the operator profile
        # (which is the only mode this subscriber implements).
        origin = build_control_ui_origin(self._url)
        if origin:
            connect_kwargs["origin"] = origin
        while not stop.is_set():
            self._events_dispatched_this_connection = 0
            try:
                async with websockets.connect(self._url, **connect_kwargs) as ws:
                    if await self._handshake_and_subscribe(ws):
                        await self._listen(ws, stop)
                    # Else: bad challenge / silent gateway / non-protocol
                    # first frame / connect res not ok. Don't subscribe;
                    # exit the context manager (closes WS) and fall
                    # through to the backoff path below.
            except ConnectionClosed:
                logger.info("gateway WS connection closed; will reconnect")
            except Exception:
                logger.exception("gateway WS connect failed; will retry")
            if stop.is_set():
                return
            # Reset backoff only after a connection that ACTUALLY
            # delivered work — handshake completion alone isn't enough
            # because a misconfigured token or silent gateway can
            # complete the handshake (or time it out at the same
            # threshold) without ever streaming events.
            if self._events_dispatched_this_connection > 0:
                delay = self._initial_delay
            await self._sleep_with_stop(delay, stop)
            delay = min(delay * 2, self._max_delay)

    # --- handshake + subscribe ---

    async def _handshake_and_subscribe(self, ws: Any) -> bool:
        """Receive ``connect.challenge``, send ``connect`` req with the
        echoed nonce, then send one ``req`` per subscription.

        Returns ``True`` iff the handshake completed against a valid
        ``connect.challenge`` frame; ``False`` if the gateway timed out,
        sent non-JSON, or sent a frame that wasn't ``connect.challenge``.
        On ``False``, the caller MUST NOT send any subscribe reqs and
        SHOULD close the connection (let the outer loop reconnect with
        backoff).
        """
        try:
            first_raw = await asyncio.wait_for(ws.recv(), timeout=self._handshake_timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "gateway did not send %s within %ss",
                EVENT_CONNECT_CHALLENGE,
                self._handshake_timeout_seconds,
            )
            return False
        try:
            first = json.loads(first_raw if isinstance(first_raw, str) else first_raw.decode())
        except json.JSONDecodeError:
            logger.warning("gateway sent non-JSON first frame; aborting handshake")
            return False
        if not (
            isinstance(first, dict)
            and first.get("type") == FRAME_TYPE_EVENT
            and first.get("event") == EVENT_CONNECT_CHALLENGE
        ):
            logger.warning(
                "gateway first frame was not %s (got type=%s event=%s); aborting handshake",
                EVENT_CONNECT_CHALLENGE,
                first.get("type") if isinstance(first, dict) else type(first).__name__,
                first.get("event") if isinstance(first, dict) else None,
            )
            return False
        # The challenge nonce is read but discarded in control-UI mode:
        # the gateway only validates the nonce inside a `device` payload
        # (which we don't send). Reading it here keeps the recv stream
        # advanced past the challenge frame.

        connect_params = build_control_ui_connect_params(
            token=self._token,
            protocol_version=self._protocol_version,
        )
        connect_id = await self._send_req(ws, METHOD_CONNECT, connect_params)
        if not await self._await_ok_res(ws, connect_id):
            return False
        for method in self._subscriptions:
            await self._send_req(ws, method, {})
        return True

    async def _send_req(self, ws: Any, method: str, params: dict[str, Any]) -> str:
        request_id = str(uuid4())
        message = {
            "type": FRAME_TYPE_REQ,
            "id": request_id,
            "method": method,
            "params": params,
        }
        await ws.send(json.dumps(message))
        return request_id

    async def _await_ok_res(self, ws: Any, request_id: str) -> bool:
        """Wait for ``{"type":"res","id":<request_id>,"ok":true}``.

        Returns ``False`` on timeout, on ``ok:false`` with logged
        error detail, or on a closed connection. Frames that aren't
        the matching res are skipped (events arriving pre-subscribe
        are rare but possible — the subscriber does not buffer them
        for later dispatch since ``_dispatch`` will see them on the
        next iteration if the connection survives, which it won't if
        we returned False here).
        """
        deadline = asyncio.get_event_loop().time() + _CONNECT_RES_TIMEOUT_SECONDS
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(
                    "no res for connect req within %ss; aborting", _CONNECT_RES_TIMEOUT_SECONDS
                )
                return False
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.warning(
                    "no res for connect req within %ss; aborting", _CONNECT_RES_TIMEOUT_SECONDS
                )
                return False
            try:
                msg = json.loads(raw if isinstance(raw, str) else raw.decode())
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != FRAME_TYPE_RES or msg.get("id") != request_id:
                # Skip unrelated frames (events, other res), keep waiting.
                continue
            if msg.get("ok") is False:
                err = msg.get("error") or {}
                err_msg = err.get("message") if isinstance(err, dict) else None
                logger.warning("connect rejected by gateway: %s", err_msg or "no message")
                return False
            return True

    # --- listen + dispatch ---

    async def _listen(self, ws: Any, stop: asyncio.Event) -> None:
        recv_task = asyncio.create_task(self._recv_loop(ws))
        stop_task = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait(
                {recv_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                await ws.close()
            # If recv_task finished by raising (transport OSError,
            # TimeoutError mid-stream, etc.), pull the exception so it
            # gets logged instead of asyncio's "Task exception was
            # never retrieved" warning at GC time. Codex post-cleanup
            # finding (2026-05-03).
            if recv_task in done:
                exc = recv_task.exception()
                if exc is not None and not isinstance(exc, ConnectionClosed):
                    logger.warning("recv loop raised: %s", exc)
        finally:
            for t in (recv_task, stop_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, ConnectionClosed):
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
        if payload.get("type") != FRAME_TYPE_EVENT:
            return
        event_name = payload.get("event")
        if not isinstance(event_name, str):
            return
        handler = self._handlers.get(event_name)
        if handler is None:
            return
        # Track that the connection actually delivered work — used by
        # ``run()`` to decide whether to reset reconnect backoff.
        # Increment BEFORE calling the handler so a handler raising
        # still counts as "the gateway gave us a real event".
        self._events_dispatched_this_connection += 1
        try:
            await handler(payload)
        except Exception:
            logger.exception("handler for %s raised; continuing", event_name)

    async def _sleep_with_stop(self, seconds: float, stop: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
