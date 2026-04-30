# ruff: noqa
"""Tests for the per-IP rate limiter applied to ``get_auth_context``.

Guards against brute-force token validation regardless of which protected
``/api/v1/*`` endpoint an attacker probes. The limiter sits at the very start
of ``get_auth_context`` / ``get_auth_context_optional``, before any token
parsing or DB lookup, so 429s are cheap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request, status

from app.core import auth, rate_limit
from app.core.rate_limit import InMemoryRateLimiter


def _fake_request(client_ip: str = "203.0.113.5") -> Request:
    """Build a minimal Starlette Request whose `request.client.host` is set."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/users/me",
        "headers": [],
        "client": (client_ip, 56789),
        "query_string": b"",
        "raw_path": b"/api/v1/users/me",
        "scheme": "https",
        "server": ("mc-api.tobyops.com", 443),
        "root_path": "",
        "app": None,
    }
    return Request(scope)


def test_user_auth_limiter_default_threshold_is_120_per_minute() -> None:
    assert isinstance(rate_limit.user_auth_limiter, rate_limit.RateLimiter)
    if isinstance(rate_limit.user_auth_limiter, InMemoryRateLimiter):
        assert rate_limit.user_auth_limiter._max_requests == 120
        assert rate_limit.user_auth_limiter._window_seconds == 60.0


@pytest.mark.asyncio
async def test_get_auth_context_returns_429_when_limiter_blocks() -> None:
    """A blocked IP must short-circuit before any token parse / DB lookup."""

    blocking_limiter = AsyncMock()
    blocking_limiter.is_allowed.return_value = False

    request = _fake_request()
    with patch.object(auth, "user_auth_limiter", blocking_limiter):
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_auth_context(request=request)

    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    blocking_limiter.is_allowed.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_auth_context_optional_returns_429_when_limiter_blocks() -> None:
    blocking_limiter = AsyncMock()
    blocking_limiter.is_allowed.return_value = False

    request = _fake_request()
    with patch.object(auth, "user_auth_limiter", blocking_limiter):
        with pytest.raises(HTTPException) as exc_info:
            await auth.get_auth_context_optional(request=request)

    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_get_auth_context_optional_skips_limiter_for_agent_token_requests() -> None:
    """Agent-token paths are governed by the separate agent_auth limiter."""

    blocking_limiter = AsyncMock()
    blocking_limiter.is_allowed.return_value = False

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/agent/boards/abc",
        "headers": [(b"x-agent-token", b"some-token")],
        "client": ("203.0.113.5", 56789),
        "query_string": b"",
        "raw_path": b"/api/v1/agent/boards/abc",
        "scheme": "https",
        "server": ("mc-api.tobyops.com", 443),
        "root_path": "",
        "app": None,
    }
    request = Request(scope)

    with patch.object(auth, "user_auth_limiter", blocking_limiter):
        result = await auth.get_auth_context_optional(request=request)

    # The function returns None for agent-token requests *without* consulting
    # the user_auth_limiter, so a blocking mock here proves the early return
    # ran first.
    assert result is None
    blocking_limiter.is_allowed.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_auth_limiter_blocks_after_threshold_per_ip() -> None:
    """Direct exercise of the limiter logic — sanity check on the configured threshold."""

    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60.0)
    ip = "203.0.113.7"

    assert await limiter.is_allowed(ip) is True
    assert await limiter.is_allowed(ip) is True
    assert await limiter.is_allowed(ip) is True
    assert await limiter.is_allowed(ip) is False

    # Independent IPs are tracked independently.
    assert await limiter.is_allowed("198.51.100.99") is True
