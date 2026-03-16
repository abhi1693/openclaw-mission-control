"""Tests for rate limiters (in-memory and Redis-backed)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.rate_limit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    create_rate_limiter,
    validate_rate_limit_redis,
)
from app.core.rate_limit_backend import RateLimitBackend


class _FakeRedis:
    """Minimal in-process Redis fake supporting the limiter Lua script."""

    def __init__(self) -> None:
        self._sorted_sets: dict[str, dict[str, float]] = {}

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        cutoff: float,
        now: float,
        member: str,
        max_requests: int,
        ttl: int,
    ) -> int:
        del script, numkeys, ttl

        zset = self._sorted_sets.setdefault(key, {})
        expired = [m for m, s in zset.items() if s <= float(cutoff)]
        for m in expired:
            del zset[m]

        if len(zset) < int(max_requests):
            zset[member] = float(now)
            return 1

        oldest_member = min(zset, key=zset.__getitem__)
        del zset[oldest_member]
        zset[member] = float(now)
        return 0

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# InMemoryRateLimiter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_allows_requests_within_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60.0)
    for _ in range(5):
        assert await limiter.is_allowed("client-a") is True


@pytest.mark.asyncio()
async def test_blocks_requests_over_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60.0)
    for _ in range(3):
        assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False
    assert await limiter.is_allowed("client-a") is False


@pytest.mark.asyncio()
async def test_blocked_requests_extend_window_without_growing_memory() -> None:
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=1.0)
    with patch("time.monotonic", side_effect=[0.0, 0.1, 0.2, 1.05, 1.21]):
        assert await limiter.is_allowed("client-a") is True
        assert await limiter.is_allowed("client-a") is True
        assert await limiter.is_allowed("client-a") is False
        assert await limiter.is_allowed("client-a") is False
        assert await limiter.is_allowed("client-a") is True

    assert len(limiter._buckets["client-a"]) == 2


@pytest.mark.asyncio()
async def test_separate_keys_have_independent_limits() -> None:
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60.0)
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False
    # Different key still allowed
    assert await limiter.is_allowed("client-b") is True
    assert await limiter.is_allowed("client-b") is True
    assert await limiter.is_allowed("client-b") is False


@pytest.mark.asyncio()
async def test_window_expiry_resets_limit() -> None:
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=1.0)
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False

    # Simulate time passing beyond the window
    future = time.monotonic() + 2.0
    with patch("time.monotonic", return_value=future):
        assert await limiter.is_allowed("client-a") is True


@pytest.mark.asyncio()
async def test_sweep_removes_expired_keys() -> None:
    """Keys whose timestamps have all expired should be evicted during periodic sweep."""
    from app.core.rate_limit import _CLEANUP_INTERVAL

    limiter = InMemoryRateLimiter(max_requests=100, window_seconds=1.0)

    # Fill with many unique IPs
    for i in range(10):
        await limiter.is_allowed(f"stale-{i}")

    assert len(limiter._buckets) == 10

    # Advance time so all timestamps expire, then trigger enough calls to
    # hit the cleanup interval.
    future = time.monotonic() + 2.0
    with patch("time.monotonic", return_value=future):
        # Drive the call count up to a multiple of _CLEANUP_INTERVAL
        remaining = _CLEANUP_INTERVAL - (limiter._call_count % _CLEANUP_INTERVAL)
        for i in range(remaining):
            await limiter.is_allowed("trigger-sweep")

    # Stale keys should have been swept; only "trigger-sweep" should remain
    assert "stale-0" not in limiter._buckets
    assert "trigger-sweep" in limiter._buckets


# ---------------------------------------------------------------------------
# RedisRateLimiter tests
# ---------------------------------------------------------------------------


def _make_redis_limiter(
    fake: _FakeRedis,
    *,
    namespace: str = "test",
    max_requests: int = 5,
    window_seconds: float = 60.0,
) -> RedisRateLimiter:
    """Build a RedisRateLimiter wired to a _FakeRedis instance."""
    with patch("app.core.rate_limit._get_async_redis", return_value=fake):
        return RedisRateLimiter(
            namespace=namespace,
            max_requests=max_requests,
            window_seconds=window_seconds,
            redis_url="redis://fake:6379/0",
        )


@pytest.mark.asyncio()
async def test_redis_allows_within_limit() -> None:
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=5)
    for _ in range(5):
        assert await limiter.is_allowed("client-a") is True


@pytest.mark.asyncio()
async def test_redis_blocks_over_limit() -> None:
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=3)
    for _ in range(3):
        assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False
    assert await limiter.is_allowed("client-a") is False


@pytest.mark.asyncio()
async def test_redis_blocked_requests_extend_window_without_growing_storage() -> None:
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=2, window_seconds=1.0)
    redis_key = "ratelimit:test:client-a"

    with patch("time.time", side_effect=[0.0, 0.1, 0.2, 1.05, 1.21]):
        assert await limiter.is_allowed("client-a") is True
        assert await limiter.is_allowed("client-a") is True
        assert await limiter.is_allowed("client-a") is False
        assert await limiter.is_allowed("client-a") is False
        assert await limiter.is_allowed("client-a") is True

    assert len(fake._sorted_sets[redis_key]) == 2


@pytest.mark.asyncio()
async def test_redis_separate_keys_independent() -> None:
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=2)
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False
    # Different key still allowed
    assert await limiter.is_allowed("client-b") is True
    assert await limiter.is_allowed("client-b") is True
    assert await limiter.is_allowed("client-b") is False


@pytest.mark.asyncio()
async def test_redis_window_expiry() -> None:
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=2, window_seconds=1.0)
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is False

    # Simulate time passing beyond the window
    future = time.time() + 2.0
    with patch("time.time", return_value=future):
        assert await limiter.is_allowed("client-a") is True


@pytest.mark.asyncio()
async def test_redis_fail_open_on_error() -> None:
    """When Redis is unreachable, requests should be allowed (fail-open)."""
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=1)

    broken_eval = MagicMock(side_effect=ConnectionError("Redis gone"))
    limiter._client.eval = broken_eval  # type: ignore[assignment]

    # Should still allow (fail-open) even though Redis is broken
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True  # would normally be blocked


@pytest.mark.asyncio()
async def test_redis_fail_open_logs_warning() -> None:
    """Verify a warning is logged when Redis is unreachable."""
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=1)

    limiter._client.eval = MagicMock(side_effect=ConnectionError("Redis gone"))  # type: ignore[assignment]

    with patch("app.core.rate_limit.logger") as mock_logger:
        await limiter.is_allowed("client-a")
        mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_factory_returns_memory_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.rate_limit_backend", RateLimitBackend.MEMORY)
    limiter = create_rate_limiter(namespace="test", max_requests=10, window_seconds=60.0)
    assert isinstance(limiter, InMemoryRateLimiter)


def test_factory_returns_redis_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.rate_limit_backend", RateLimitBackend.REDIS)
    monkeypatch.setattr("app.core.config.settings.rate_limit_redis_url", "redis://localhost:6379/0")
    fake = _FakeRedis()
    with patch("app.core.rate_limit._get_async_redis", return_value=fake):
        limiter = create_rate_limiter(namespace="test", max_requests=10, window_seconds=60.0)
    assert isinstance(limiter, RedisRateLimiter)


# ---------------------------------------------------------------------------
# Startup validation tests
# ---------------------------------------------------------------------------


def test_validate_redis_succeeds_when_reachable() -> None:
    fake = _FakeRedis()
    with patch("redis.Redis.from_url", return_value=fake):
        validate_rate_limit_redis("redis://localhost:6379/0")


def test_validate_redis_raises_on_unreachable() -> None:
    mock_client = MagicMock()
    mock_client.ping.side_effect = ConnectionError("refused")
    with patch("redis.Redis.from_url", return_value=mock_client):
        with pytest.raises(ConnectionError, match="unreachable"):
            validate_rate_limit_redis("redis://bad:6379/0")
