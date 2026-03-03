"""Tests for the in-memory rate limiter."""

from __future__ import annotations

import time
from unittest.mock import patch

from app.core.rate_limit import InMemoryRateLimiter


def test_allows_requests_within_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60.0)
    for _ in range(5):
        assert limiter.is_allowed("client-a") is True


def test_blocks_requests_over_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60.0)
    for _ in range(3):
        assert limiter.is_allowed("client-a") is True
    assert limiter.is_allowed("client-a") is False
    assert limiter.is_allowed("client-a") is False


def test_separate_keys_have_independent_limits() -> None:
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60.0)
    assert limiter.is_allowed("client-a") is True
    assert limiter.is_allowed("client-a") is True
    assert limiter.is_allowed("client-a") is False
    # Different key still allowed
    assert limiter.is_allowed("client-b") is True
    assert limiter.is_allowed("client-b") is True
    assert limiter.is_allowed("client-b") is False


def test_window_expiry_resets_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=1.0)
    assert limiter.is_allowed("client-a") is True
    assert limiter.is_allowed("client-a") is True
    assert limiter.is_allowed("client-a") is False

    # Simulate time passing beyond the window
    future = time.monotonic() + 2.0
    with patch("time.monotonic", return_value=future):
        assert limiter.is_allowed("client-a") is True


def test_sweep_removes_expired_keys() -> None:
    """Keys whose timestamps have all expired should be evicted during periodic sweep."""
    from app.core.rate_limit import _CLEANUP_INTERVAL

    limiter = InMemoryRateLimiter(max_requests=100, window_seconds=1.0)

    # Fill with many unique IPs
    for i in range(10):
        limiter.is_allowed(f"stale-{i}")

    assert len(limiter._buckets) == 10

    # Advance time so all timestamps expire, then trigger enough calls to
    # hit the cleanup interval.
    future = time.monotonic() + 2.0
    with patch("time.monotonic", return_value=future):
        # Drive the call count up to a multiple of _CLEANUP_INTERVAL
        remaining = _CLEANUP_INTERVAL - (limiter._call_count % _CLEANUP_INTERVAL)
        for i in range(remaining):
            limiter.is_allowed("trigger-sweep")

    # Stale keys should have been swept; only "trigger-sweep" should remain
    assert "stale-0" not in limiter._buckets
    assert "trigger-sweep" in limiter._buckets
