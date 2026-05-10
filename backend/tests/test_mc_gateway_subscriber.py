"""Connection-lifecycle + protocol tests for the gateway event subscriber.

Per the live `app/services/openclaw/gateway_rpc.py` client, the
OpenClaw gateway protocol is:

  - WebSocket transport, JSON messages.
  - Server sends ``{"type":"event","event":"connect.challenge",
    "payload":{"nonce":"..."}}`` immediately after handshake.
  - Client must reply with
    ``{"type":"req","id":<uuid>,"method":"connect","params":{...}}``.
  - Server replies with ``{"type":"res","id":<id>,"ok":true,...}``.
  - After ``connect``, client sends one ``req`` per subscription
    (e.g. ``sessions.subscribe``).
  - Events thereafter arrive as
    ``{"type":"event","event":"<name>","payload":{...}}``.

Subscriber MUST:
  T1. Connect, send the ``connect`` req with operator scopes, then send
      one subscribe req per configured subscription topic.
  T2. Survive a connection drop with exponential-backoff reconnect, and
      re-issue the connect handshake + subscriptions on each reconnect.
  T3. Stop cleanly when the caller sets ``asyncio.Event``.
  T4. Dispatch each incoming ``event`` message to handlers registered
      with ``.on(event_name, fn)``.
  T5. Survive handler exceptions; the next event still dispatches.
  T6. Silently skip events with no registered handler.

Per ``feedback_tdd_discipline``: this file expresses the contract the
``Subscriber`` MUST satisfy. Implementation can change so long as
these assertions still pass.
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
async def stub_gateway():
    """Spin a websockets server that speaks the OpenClaw connect handshake.

    The server:
      1. On each new connection, immediately sends the ``connect.challenge``
         event with a random nonce.
      2. Receives the client's ``connect`` req and replies with a synthetic
         ok ``res``.
      3. Receives subscription reqs and replies with ok ``res``.
      4. Forwards arbitrary events queued by the test back to the client.

    Exposes a handle for tests to drive event delivery and inspect the
    sub-messages the client sent.
    """
    sent_to_server: list[dict[str, Any]] = []
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    connections: list[Any] = []
    headers_seen: list[dict[str, str]] = []

    async def handler(ws):
        connections.append(ws)
        headers_seen.append(dict(ws.request.headers))
        # 1. Send connect.challenge.
        await ws.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": "stub-nonce-xyz"},
                }
            )
        )

        async def receive_loop() -> None:
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    msg = json.loads(raw)
                    sent_to_server.append(msg)
                    # Reply ok to any req.
                    if msg.get("type") == "req":
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "res",
                                    "id": msg.get("id"),
                                    "ok": True,
                                    "payload": {"echo": msg.get("method")},
                                }
                            )
                        )
            except websockets.exceptions.ConnectionClosed:
                pass

        async def event_driver() -> None:
            try:
                while True:
                    item = await event_queue.get()
                    if item is None:
                        await ws.close()
                        return
                    await ws.send(json.dumps(item))
            except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                pass

        event_task = asyncio.create_task(event_driver())
        try:
            await receive_loop()
        finally:
            event_task.cancel()
            try:
                await event_task
            except (asyncio.CancelledError, Exception):
                pass

    server = await websockets.serve(handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]

    class Handle:
        url = f"ws://127.0.0.1:{port}"

        @staticmethod
        async def push_event(event_name: str, payload: dict[str, Any] | None = None) -> None:
            await event_queue.put(
                {
                    "type": "event",
                    "event": event_name,
                    "payload": payload or {},
                }
            )

        @staticmethod
        async def kick_connection() -> None:
            if connections:
                await connections[-1].close()

        @staticmethod
        def server_received() -> list[dict[str, Any]]:
            return list(sent_to_server)

        @staticmethod
        def connection_count() -> int:
            return len(connections)

        @staticmethod
        def headers_first() -> dict[str, str]:
            return headers_seen[0] if headers_seen else {}

    try:
        yield Handle
    finally:
        server.close()
        await server.wait_closed()


async def _wait_for(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)


# --- T1: connect handshake + subscribe at start ---


@pytest.mark.asyncio
async def test_subscriber_sends_connect_then_subscribe(stub_gateway) -> None:
    """On connect, subscriber sends a ``connect`` req then one ``req`` per
    subscription topic, in order, with a unique ``id`` each.
    """
    handle = stub_gateway
    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=["sessions.subscribe", "sessions.messages.subscribe"],
        reconnect_initial_delay=0.05,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: len(handle.server_received()) >= 3)

    msgs = handle.server_received()
    assert msgs[0]["type"] == "req"
    assert msgs[0]["method"] == "connect"
    assert msgs[1]["type"] == "req"
    assert msgs[1]["method"] == "sessions.subscribe"
    assert msgs[2]["type"] == "req"
    assert msgs[2]["method"] == "sessions.messages.subscribe"
    # Distinct ids.
    ids = {m["id"] for m in msgs[:3]}
    assert len(ids) == 3

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T2: bearer auth on handshake ---


@pytest.mark.asyncio
async def test_subscriber_sends_bearer_token_on_connect(stub_gateway) -> None:
    handle = stub_gateway
    sub = Subscriber(
        url=handle.url,
        token="my-secret-token",
        subscriptions=[],
        reconnect_initial_delay=0.05,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: bool(handle.headers_first()))
    auth = handle.headers_first().get("Authorization") or handle.headers_first().get(
        "authorization"
    )
    assert auth == "Bearer my-secret-token"
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T3: reconnect after drop, re-handshake + re-subscribe ---


@pytest.mark.asyncio
async def test_subscriber_reconnects_and_resubscribes(stub_gateway) -> None:
    handle = stub_gateway
    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=["sessions.subscribe"],
        reconnect_initial_delay=0.05,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    # First connect: connect + subscribe = 2 reqs.
    await _wait_for(lambda: len(handle.server_received()) >= 2)
    assert handle.connection_count() == 1

    await handle.kick_connection()
    # Second connect: another connect + subscribe = 4 total.
    await _wait_for(lambda: handle.connection_count() >= 2 and len(handle.server_received()) >= 4)
    msgs = handle.server_received()
    methods = [m.get("method") for m in msgs if m.get("type") == "req"]
    # Order on each connect: connect, then subscribe.
    assert methods[:2] == ["connect", "sessions.subscribe"]
    assert methods[2:4] == ["connect", "sessions.subscribe"]

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T4: dispatch event to registered handler ---


@pytest.mark.asyncio
async def test_subscriber_dispatches_event_by_name(stub_gateway) -> None:
    handle = stub_gateway
    received_events: list[dict[str, Any]] = []

    async def on_changed(payload: dict[str, Any]) -> None:
        received_events.append(payload)

    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=["sessions.subscribe"],
        reconnect_initial_delay=0.05,
    )
    sub.on("sessions.changed", on_changed)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: handle.connection_count() >= 1)

    await handle.push_event("sessions.changed", {"agent": "lead-x"})
    await _wait_for(lambda: len(received_events) >= 1)

    assert received_events[0]["event"] == "sessions.changed"
    assert received_events[0]["payload"]["agent"] == "lead-x"

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T5: handler exception doesn't crash subscriber ---


@pytest.mark.asyncio
async def test_subscriber_handler_exception_does_not_crash(stub_gateway) -> None:
    handle = stub_gateway
    call_count = 0

    async def bad_handler(payload: dict[str, Any]) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated bug")

    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=[],
        reconnect_initial_delay=0.05,
    )
    sub.on("sessions.changed", bad_handler)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: handle.connection_count() >= 1)

    await handle.push_event("sessions.changed", {"i": 1})
    await handle.push_event("sessions.changed", {"i": 2})
    await _wait_for(lambda: call_count >= 2)

    assert not task.done()
    assert call_count >= 2

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T6: unknown events silently skipped ---


@pytest.mark.asyncio
async def test_subscriber_skips_unknown_events(stub_gateway) -> None:
    handle = stub_gateway
    seen: list[dict[str, Any]] = []

    async def only_changed(payload: dict[str, Any]) -> None:
        seen.append(payload)

    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=[],
        reconnect_initial_delay=0.05,
    )
    sub.on("sessions.changed", only_changed)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: handle.connection_count() >= 1)

    await handle.push_event("presence", {"x": 1})
    await handle.push_event("sessions.changed", {"x": 2})
    await handle.push_event("tick", {"x": 3})
    await _wait_for(lambda: len(seen) >= 1)

    assert len(seen) == 1
    assert seen[0]["event"] == "sessions.changed"

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


# --- T7: connect.challenge nonce is reflected in connect req ---


@pytest.mark.asyncio
async def test_subscriber_does_not_reset_backoff_on_handshake_then_close(stub_gateway) -> None:
    """Codex-found bug: ``delay = self._initial_delay`` in ``run()`` was
    being reset BEFORE ``_listen`` started receiving real events.
    A misconfigured token (gateway accepts handshake then closes
    immediately) caused a 1-Hz reconnect storm. Backoff must escalate
    when a connection drops without ever delivering an event.

    Repro: configure the stub to close every connection right after the
    handshake. Capture the elapsed time across N reconnects; with the
    bug it's roughly N * initial_delay (linear in attempts), with the
    fix it's a geometric series (exponential).
    """
    # Counts how many times the stub server accepts a connection.
    accept_count = 0
    delays_observed: list[float] = []
    last_accept_time: list[float] = []

    async def closing_handler(ws):
        nonlocal accept_count
        now = asyncio.get_event_loop().time()
        if last_accept_time:
            delays_observed.append(now - last_accept_time[-1])
        last_accept_time.append(now)
        accept_count += 1
        # Send the challenge so handshake proceeds (so reconnect logic is
        # exercised AFTER a handshake). Then immediately close.
        await ws.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": "stub-n"},
                }
            )
        )
        await asyncio.sleep(0.01)  # let subscriber send connect req
        await ws.close()

    server = await websockets.serve(closing_handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    sub = Subscriber(
        url=url,
        token="t",
        subscriptions=[],
        reconnect_initial_delay=0.05,
        reconnect_max_delay=5.0,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    # Wait until we've observed enough reconnects to compare delays.
    await _wait_for(lambda: accept_count >= 4, timeout=4.0, interval=0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    server.close()
    await server.wait_closed()

    # Bug version (delay reset every connect): delays_observed[1] ≈ delays_observed[0] (both ~0.05s).
    # Fixed version (delay escalates while connection is unhealthy): delays_observed[1] > delays_observed[0].
    assert len(delays_observed) >= 2, f"need at least 2 inter-connect deltas, got {delays_observed}"
    assert (
        delays_observed[1] > delays_observed[0] * 1.5
    ), f"backoff did not escalate after handshake-then-close: deltas={delays_observed}"


@pytest.mark.asyncio
async def test_subscriber_aborts_handshake_when_first_frame_is_not_challenge(
    stub_gateway,
) -> None:
    """Codex-found bug: if the gateway's first frame is valid JSON but not
    a ``connect.challenge`` event, the subscriber used to fall through and
    send the ``connect`` req anyway. That hides protocol drift behind a
    silent reconnect loop. Subscriber must NOT send ``connect`` (or any
    subscribe) on a bad first frame, and must close the WS to trigger
    backoff.
    """
    sent_to_server: list[dict[str, Any]] = []

    async def confused_handler(ws):
        # First frame: valid JSON but completely wrong shape.
        await ws.send(json.dumps({"type": "event", "event": "presence", "payload": {}}))
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                sent_to_server.append(json.loads(raw))
        except websockets.exceptions.ConnectionClosed:
            pass

    server = await websockets.serve(confused_handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    sub = Subscriber(
        url=url,
        token="t",
        subscriptions=["sessions.subscribe"],
        reconnect_initial_delay=0.05,
        reconnect_max_delay=0.2,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))

    # Give it 0.5s — long enough to attempt the handshake, abort, and
    # try at least one reconnect.
    await asyncio.sleep(0.5)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    server.close()
    await server.wait_closed()

    # The bug version sent a `connect` req anyway. The fix must not.
    methods = [m.get("method") for m in sent_to_server if m.get("type") == "req"]
    assert (
        "connect" not in methods
    ), f"subscriber sent connect req against a non-challenge first frame: methods={methods}"


@pytest.mark.asyncio
async def test_subscriber_does_not_subscribe_when_connect_res_is_not_ok(
    stub_gateway,
) -> None:
    """Codex post-cleanup finding: subscriber sent the ``connect`` req
    but never awaited the gateway's response. If the gateway replies
    ``{"type":"res","ok":false,...}`` (bad token, scope mismatch,
    expired pairing), the subscriber proceeded to send subscribe reqs
    anyway — and ``_dispatch`` ignored the error res because it wasn't
    an event. The worker sat "connected" with auth actually failed.

    Contract: when the connect res returns ``ok:false``, NO subscribe
    req leaves the wire.
    """
    sent_to_server: list[dict[str, Any]] = []

    async def auth_failing_handler(ws):
        await ws.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": "n"},
                }
            )
        )
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                msg = json.loads(raw)
                sent_to_server.append(msg)
                if msg.get("type") == "req" and msg.get("method") == "connect":
                    await ws.send(
                        json.dumps(
                            {
                                "type": "res",
                                "id": msg["id"],
                                "ok": False,
                                "error": {"message": "bad token"},
                            }
                        )
                    )
                    # Keep the connection open after the failed res so
                    # the subscriber has a clear opportunity to send
                    # subscribe reqs (which it MUST NOT do). The test
                    # asserts after a fixed wait below.
        except websockets.exceptions.ConnectionClosed:
            pass

    server = await websockets.serve(auth_failing_handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    sub = Subscriber(
        url=url,
        token="bad",
        subscriptions=["sessions.subscribe"],
        reconnect_initial_delay=0.05,
        reconnect_max_delay=0.2,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await asyncio.sleep(0.4)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    server.close()
    await server.wait_closed()

    methods = [m.get("method") for m in sent_to_server if m.get("type") == "req"]
    assert (
        "sessions.subscribe" not in methods
    ), f"subscriber sent subscribe after a failed connect: methods={methods}"


@pytest.mark.asyncio
async def test_subscriber_silent_gateway_backs_off_geometrically(
    stub_gateway,
) -> None:
    """Codex post-cleanup finding: ``HEALTHY_CONNECTION_SECONDS`` (5s)
    equals the handshake timeout (5s), so a gateway that accepts the
    WS but sends nothing makes the connection look "healthy" by
    uptime alone — and backoff resets every cycle.

    Real signal of "healthy" should be at least one event delivered.
    Test: silent gateway → backoff escalates between attempts
    (geometric, not flat).
    """
    accept_times: list[float] = []

    async def silent_handler(ws):
        accept_times.append(asyncio.get_event_loop().time())
        # Don't send the challenge. Just close the connection after the
        # subscriber's handshake timeout fires (subscriber will return
        # False from _handshake_and_subscribe and reconnect). A long
        # sleep here would block fixture teardown.
        try:
            await asyncio.wait_for(ws.wait_closed(), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    server = await websockets.serve(silent_handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    # Tight timeout + tight initial delay so the test runs fast.
    # Override the production handshake timeout via a per-instance
    # field if available; otherwise we measure with the default.
    sub = Subscriber(
        url=url,
        token="t",
        subscriptions=[],
        reconnect_initial_delay=0.05,
        reconnect_max_delay=2.0,
    )
    # Shrink the handshake timeout for this test specifically.
    sub._handshake_timeout_seconds = 0.1
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    # Wait long enough for at least 3 accepts.
    await _wait_for(lambda: len(accept_times) >= 3, timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    server.close()
    await server.wait_closed()

    deltas = [accept_times[i + 1] - accept_times[i] for i in range(len(accept_times) - 1)]
    assert len(deltas) >= 2
    # Bug version: each attempt waits ~handshake_timeout + initial_delay,
    # roughly flat. Fixed version: deltas escalate geometrically.
    assert deltas[1] > deltas[0], f"silent-gateway path did not escalate backoff: deltas={deltas}"


@pytest.mark.asyncio
async def test_subscriber_module_imports_with_minimal_env() -> None:
    """Codex post-cleanup finding: importing the subscriber pulled in
    ``app.services.openclaw.gateway_rpc`` → ``app.core.logging`` →
    ``app.core.config``, which instantiates ``Settings()`` requiring
    ``auth_mode`` and ``BASE_URL``. The subscriber is supposed to
    deploy with just ``OPENCLAW_GATEWAY_WS_URL`` /
    ``OPENCLAW_GATEWAY_TOKEN`` per its README. Importing must not
    require the full MC backend env.

    Contract: ``import app.services.mc_gateway_subscriber.subscriber``
    succeeds in a process with NO MC config env vars.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import app.services.mc_gateway_subscriber.subscriber"],
        cwd=str(repo_root),
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"subscriber import failed without MC env:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


@pytest.mark.asyncio
async def test_subscriber_sends_control_ui_client_identity(stub_gateway) -> None:
    """The gateway only accepts a fixed allow-list of ``client.id`` /
    ``client.mode`` values and requires ``client.platform``. Backend
    subscribers connect in control-UI mode (no device-pairing crypto), so
    the connect req must carry the canonical control-UI identity and
    drop ``connectNonce`` (which is only valid inside the ``device``
    payload that control-UI mode doesn't send).
    """
    handle = stub_gateway
    sub = Subscriber(
        url=handle.url,
        token="t",
        subscriptions=[],
        reconnect_initial_delay=0.05,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    await _wait_for(lambda: len(handle.server_received()) >= 1)
    connect_req = handle.server_received()[0]
    assert connect_req["method"] == "connect"
    params = connect_req.get("params", {})
    client = params.get("client", {})
    assert client.get("id") == "openclaw-control-ui"
    assert client.get("mode") == "ui"
    assert client.get("platform"), "client.platform is required by the gateway"
    assert (
        "connectNonce" not in params
    ), "connectNonce at root is rejected by the gateway in control-UI mode"
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
