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

# ---------------------------------------------------------------------------
# Fake Redis helpers for deterministic testing
# ---------------------------------------------------------------------------


class _FakePipeline:
    """Minimal sorted-set pipeline that executes against a _FakeRedis."""

    def __init__(self, parent: _FakeRedis) -> None:
        self._parent = parent
        self._ops: list[tuple[str, ...]] = []

    # Pipeline command stubs -- each just records intent and returns self
    # so chaining works (even though our tests don't chain).

    def zremrangebyscore(self, key: str, min_val: str, max_val: float) -> _FakePipeline:
        self._ops.append(("zremrangebyscore", key, str(min_val), str(max_val)))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> _FakePipeline:
        self._ops.append(("zadd", key, *next(iter(mapping.items()))))
        return self

    def zcard(self, key: str) -> _FakePipeline:
        self._ops.append(("zcard", key))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._ops.append(("expire", key, str(seconds)))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for op in self._ops:
            cmd = op[0]
            key = op[1]
            zset = self._parent._sorted_sets.setdefault(key, {})
            if cmd == "zremrangebyscore":
                max_score = float(op[3])
                expired = [m for m, s in zset.items() if s <= max_score]
                for m in expired:
                    del zset[m]
                results.append(len(expired))
            elif cmd == "zadd":
                member, score = op[2], float(op[3])
                zset[member] = score
                results.append(1)
            elif cmd == "zcard":
                results.append(len(zset))
            elif cmd == "expire":
                results.append(True)
        return results


class _FakeRedis:
    """Minimal in-process Redis fake supporting sorted-set pipeline ops."""

    def __init__(self) -> None:
        self._sorted_sets: dict[str, dict[str, float]] = {}

    def pipeline(self, *, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)

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
    with patch("redis.asyncio.from_url", return_value=fake):
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

    # Make the pipeline raise on execute
    def _broken_pipeline(*, transaction: bool = True) -> MagicMock:
        pipe = MagicMock()
        pipe.zremrangebyscore.return_value = pipe
        pipe.zadd.return_value = pipe
        pipe.zcard.return_value = pipe
        pipe.expire.return_value = pipe
        pipe.execute.side_effect = ConnectionError("Redis gone")
        return pipe

    limiter._client.pipeline = _broken_pipeline  # type: ignore[assignment]

    # Should still allow (fail-open) even though Redis is broken
    assert await limiter.is_allowed("client-a") is True
    assert await limiter.is_allowed("client-a") is True  # would normally be blocked


@pytest.mark.asyncio()
async def test_redis_fail_open_logs_warning() -> None:
    """Verify a warning is logged when Redis is unreachable."""
    fake = _FakeRedis()
    limiter = _make_redis_limiter(fake, max_requests=1)

    def _broken_pipeline(*, transaction: bool = True) -> MagicMock:
        pipe = MagicMock()
        pipe.zremrangebyscore.return_value = pipe
        pipe.zadd.return_value = pipe
        pipe.zcard.return_value = pipe
        pipe.expire.return_value = pipe
        pipe.execute.side_effect = ConnectionError("Redis gone")
        return pipe

    limiter._client.pipeline = _broken_pipeline  # type: ignore[assignment]

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
    with patch("redis.asyncio.from_url", return_value=fake):
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
