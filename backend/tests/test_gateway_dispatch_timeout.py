# ruff: noqa: INP001
"""``try_send_agent_message`` must time out instead of hanging forever.

Repro from 2026-05-02 (15:06–16:21 UTC): an agent on the gateway POSTed
a comment, MC's comment-notify path called ``try_send_agent_message``
to wake mentioned agents, the gateway WebSocket hung, and the helper
blocked for 62-74 minutes. The MC request thread was held open the
entire time — same Comment POST eventually returned 200 OK after
``duration_ms=4484215`` (74.7 min). Until the helper has a finite
timeout, any gateway-side instability (restart, deploy, network hiccup)
can wedge MC's request pool indefinitely.

This test pins the contract: when the underlying gateway RPC hangs,
``try_send_agent_message`` must return within
``GATEWAY_NOTIFY_TIMEOUT`` seconds with an ``OpenClawGatewayError``
flagging the timeout — never let the caller block past the bound.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.openclaw.gateway_dispatch import (
    GATEWAY_NOTIFY_TIMEOUT_SECONDS,
    GatewayDispatchService,
)
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError


@pytest.mark.asyncio
async def test_try_send_agent_message_returns_within_timeout_when_gateway_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hung ``send_message`` (no response from gateway) must surface as a
    timed-out ``OpenClawGatewayError``, not block the caller indefinitely.

    Test patches the production timeout down to 0.1s so CI doesn't pay
    the real 30s ceiling on every run. The PROD value
    (``GATEWAY_NOTIFY_TIMEOUT_SECONDS=30.0``) is what protects MC's
    request pool against gateway flapping; the test only verifies the
    wait_for ceiling is honored at whatever value it is set to.
    """
    test_timeout = 0.1
    monkeypatch.setattr(
        "app.services.openclaw.gateway_dispatch.GATEWAY_NOTIFY_TIMEOUT_SECONDS",
        test_timeout,
    )

    # Patch the underlying gateway RPC layer so the call hangs forever.
    async def _hung_ensure_session(*args, **kwargs) -> None:
        await asyncio.sleep(3600)  # never resolves within the timeout

    async def _hung_send_message(*args, **kwargs) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(
        "app.services.openclaw.gateway_dispatch.ensure_session",
        _hung_ensure_session,
    )
    monkeypatch.setattr(
        "app.services.openclaw.gateway_dispatch.send_message",
        _hung_send_message,
    )

    service = GatewayDispatchService(session=None)  # session unused by helper

    config = GatewayConfig(url="ws://gateway.example.local/ws")
    started = time.monotonic()
    result = await service.try_send_agent_message(
        session_key="agent:test:session",
        config=config,
        agent_name="TestAgent",
        message="hello",
        deliver=False,
    )
    elapsed = time.monotonic() - started

    # Must return a timeout error (NOT None / NOT raise unhandled).
    assert isinstance(result, OpenClawGatewayError), (
        f"expected OpenClawGatewayError on timeout, got {type(result).__name__}: {result!r}"
    )
    # Must complete close to the patched timeout, not the 3600s sleep.
    assert elapsed < test_timeout + 1.0, (
        f"expected <{test_timeout + 1.0}s, got {elapsed:.2f}s"
    )
    # The error message should make the timeout cause auditable in logs.
    assert "timeout" in str(result).lower()


@pytest.mark.asyncio
async def test_try_send_agent_message_succeeds_when_gateway_responds_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: the timeout wrap must not break the happy path."""
    async def _ok_ensure_session(*args, **kwargs) -> None:
        return None

    async def _ok_send_message(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        "app.services.openclaw.gateway_dispatch.ensure_session",
        _ok_ensure_session,
    )
    monkeypatch.setattr(
        "app.services.openclaw.gateway_dispatch.send_message",
        _ok_send_message,
    )

    service = GatewayDispatchService(session=None)
    config = GatewayConfig(url="ws://gateway.example.local/ws")
    result = await service.try_send_agent_message(
        session_key="agent:test:session",
        config=config,
        agent_name="TestAgent",
        message="hello",
        deliver=False,
    )
    assert result is None
