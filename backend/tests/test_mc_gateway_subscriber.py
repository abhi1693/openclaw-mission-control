"""Connection-lifecycle tests for the gateway event subscriber.

This is the FIRST slice of the WS-subscription project (per
``docs/plans/2026-05-02-gateway-event-subscriber-design.md``). Scope
is deliberately narrow: connect, receive messages, reconnect on drop,
shut down cleanly. Subscription/dispatch/projection come in later
commits.

Per ``feedback_tdd_discipline``: this file expresses the contracts the
``Subscriber`` class MUST satisfy. Implementation may change so long
as these assertions still pass.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import pytest_asyncio
import websockets

from app.services.mc_gateway_subscriber.subscriber import Subscriber


@pytest_asyncio.fixture
async def stub_ws_server():
    """Spin a websockets server on a free localhost port. Yields a
    handle exposing (url, received, send_event) so tests can drive
    the subscriber lifecycle.
    """
    received: list[str] = []
    send_queue: asyncio.Queue[str | None] = asyncio.Queue()
    connections: list[Any] = []

    async def handler(ws):
        connections.append(ws)

        async def receive_loop() -> None:
            try:
                async for raw in ws:
                    received.append(raw if isinstance(raw, str) else raw.decode())
            except websockets.exceptions.ConnectionClosed:
                pass

        async def send_driver() -> None:
            try:
                while True:
                    item = await send_queue.get()
                    if item is None:
                        await ws.close()
                        return
                    await ws.send(item)
            except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                pass

        send_task = asyncio.create_task(send_driver())
        try:
            await receive_loop()
        finally:
            send_task.cancel()
            try:
                await send_task
            except (asyncio.CancelledError, Exception):
                pass

    server = await websockets.serve(handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]

    class Handle:
        url = f"ws://127.0.0.1:{port}"

        @staticmethod
        async def send_event(payload: dict[str, Any] | str) -> None:
            await send_queue.put(json.dumps(payload) if isinstance(payload, dict) else payload)

        @staticmethod
        async def kick_connection() -> None:
            """Force-close the most recent connection from the server side."""
            if connections:
                await connections[-1].close()

        @staticmethod
        def received_messages() -> list[str]:
            return list(received)

        @staticmethod
        def connection_count() -> int:
            return len(connections)

    try:
        yield Handle
    finally:
        server.close()
        await server.wait_closed()


# --- T1: connect + clean shutdown ---


@pytest.mark.asyncio
async def test_subscriber_connects_and_stops_cleanly(stub_ws_server) -> None:
    handle = stub_ws_server
    sub = Subscriber(url=handle.url, token="t", reconnect_initial_delay=0.05)
    stop = asyncio.Event()

    task = asyncio.create_task(sub.run(stop))
    # Give the connect a moment to land.
    for _ in range(40):
        if handle.connection_count() >= 1:
            break
        await asyncio.sleep(0.05)
    assert handle.connection_count() >= 1, "subscriber never connected"

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()


# --- T2: auth — Authorization: Bearer header sent on handshake ---


@pytest.mark.asyncio
async def test_subscriber_sends_bearer_token_on_connect(stub_ws_server) -> None:
    """Subscriber's WS handshake must include ``Authorization: Bearer <token>``.

    The websockets library exposes received headers via the
    ``request_headers`` attribute on the connection; we inspect via a
    dedicated server handler that captures headers.
    """
    captured_headers: list[Any] = []

    async def header_capturing_handler(ws):
        # websockets v16: request available on ws.request
        captured_headers.append(dict(ws.request.headers))
        try:
            async for _ in ws:
                pass
        except Exception:
            pass

    server = await websockets.serve(header_capturing_handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    sub = Subscriber(url=url, token="my-secret-token", reconnect_initial_delay=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    for _ in range(40):
        if captured_headers:
            break
        await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    server.close()
    await server.wait_closed()

    assert captured_headers, "no connection observed"
    auth = captured_headers[0].get("Authorization") or captured_headers[0].get("authorization")
    assert auth == "Bearer my-secret-token"


# --- T3: reconnect on drop ---


@pytest.mark.asyncio
async def test_subscriber_reconnects_after_drop(stub_ws_server) -> None:
    handle = stub_ws_server
    sub = Subscriber(url=handle.url, token="t", reconnect_initial_delay=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    # Wait for first connect.
    for _ in range(40):
        if handle.connection_count() >= 1:
            break
        await asyncio.sleep(0.05)
    assert handle.connection_count() >= 1

    # Server-side close (simulates network drop).
    await handle.kick_connection()

    # Wait for reconnect.
    for _ in range(60):
        if handle.connection_count() >= 2:
            break
        await asyncio.sleep(0.05)
    assert handle.connection_count() >= 2, "subscriber did not reconnect"

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T4: event dispatch — subscriber routes incoming JSON to a handler ---


@pytest.mark.asyncio
async def test_subscriber_dispatches_event_to_registered_handler(stub_ws_server) -> None:
    handle = stub_ws_server
    received_events: list[dict[str, Any]] = []

    async def on_node_event(payload: dict[str, Any]) -> None:
        received_events.append(payload)

    sub = Subscriber(url=handle.url, token="t", reconnect_initial_delay=0.05)
    sub.on("node.event", on_node_event)

    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    # Wait for connect, then send a synthetic event from the server side.
    for _ in range(40):
        if handle.connection_count() >= 1:
            break
        await asyncio.sleep(0.05)
    # Subscriber sends its subscribe message; stub ignores it.
    # Stub now sends a node.event back.
    await handle.send_event({"type": "node.event", "data": {"sessionKey": "agent:lead-x:s", "kind": "completed"}})
    # Subscriber needs to receive it; nudge by sending a no-op so the handler reads.
    await handle.send_event("noop")

    for _ in range(40):
        if received_events:
            break
        await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert received_events, "node.event was never dispatched"
    assert received_events[0]["type"] == "node.event"


# --- T5: handler exception doesn't crash the subscriber ---


@pytest.mark.asyncio
async def test_subscriber_handler_exception_does_not_crash(stub_ws_server) -> None:
    handle = stub_ws_server
    call_count = 0

    async def bad_handler(payload: dict[str, Any]) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated handler bug")

    sub = Subscriber(url=handle.url, token="t", reconnect_initial_delay=0.05)
    sub.on("node.event", bad_handler)

    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    for _ in range(40):
        if handle.connection_count() >= 1:
            break
        await asyncio.sleep(0.05)
    await handle.send_event({"type": "node.event", "data": {}})
    await handle.send_event({"type": "node.event", "data": {}})

    for _ in range(40):
        if call_count >= 2:
            break
        await asyncio.sleep(0.05)

    # Subscriber must still be running.
    assert not task.done(), "subscriber crashed on handler exception"
    assert call_count >= 2, "handler not retried after raising"

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T6: unknown event types are skipped silently ---


@pytest.mark.asyncio
async def test_subscriber_ignores_unregistered_event_types(stub_ws_server) -> None:
    handle = stub_ws_server
    seen: list[dict[str, Any]] = []

    async def only_node(payload: dict[str, Any]) -> None:
        seen.append(payload)

    sub = Subscriber(url=handle.url, token="t", reconnect_initial_delay=0.05)
    sub.on("node.event", only_node)

    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    for _ in range(40):
        if handle.connection_count() >= 1:
            break
        await asyncio.sleep(0.05)

    await handle.send_event({"type": "presence", "data": {}})
    await handle.send_event({"type": "node.event", "data": {"k": 1}})
    await handle.send_event({"type": "tick", "data": {}})

    for _ in range(40):
        if seen:
            break
        await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert len(seen) == 1
    assert seen[0]["type"] == "node.event"
