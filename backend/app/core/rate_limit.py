"""Sliding-window rate limiters for abuse prevention.

Supports an in-memory backend (default, no external dependencies) and
a Redis-backed backend for multi-process / distributed deployments.
Configure via RATE_LIMIT_BACKEND=memory|redis.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from threading import Lock
from typing import Awaitable, cast

import redis as redis_lib
import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.core.rate_limit_backend import RateLimitBackend

logger = get_logger(__name__)

# Run a full sweep of all keys every 128 calls to is_allowed.
_CLEANUP_INTERVAL = 128

# Redis sliding-window script that bounds per-key storage to
# ``max_requests`` while preserving the current "blocked attempts extend
# the window" behavior by retaining the most recent attempts.
_REDIS_IS_ALLOWED_SCRIPT = """
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", ARGV[1])
local count = redis.call("ZCARD", KEYS[1])
if count < tonumber(ARGV[4]) then
  redis.call("ZADD", KEYS[1], ARGV[2], ARGV[3])
  redis.call("EXPIRE", KEYS[1], ARGV[5])
  return 1
end

local oldest = redis.call("ZRANGE", KEYS[1], 0, 0)
if oldest[1] then
  redis.call("ZREM", KEYS[1], oldest[1])
end
redis.call("ZADD", KEYS[1], ARGV[2], ARGV[3])
redis.call("EXPIRE", KEYS[1], ARGV[5])
return 0
"""

# Shared async Redis clients keyed by URL to avoid duplicate connection pools.
_async_redis_clients: dict[str, aioredis.Redis] = {}


def _get_async_redis(redis_url: str) -> aioredis.Redis:
    """Return a shared async Redis client for *redis_url*, creating one if needed."""
    client = _async_redis_clients.get(redis_url)
    if client is None:
        client = aioredis.from_url(redis_url)  # type: ignore[no-untyped-call]
        _async_redis_clients[redis_url] = client
    return client


class RateLimiter(ABC):
    """Base interface for sliding-window rate limiters."""

    @abstractmethod
    async def is_allowed(self, key: str) -> bool:
        """Return True if the request should be allowed, False if rate-limited."""


class InMemoryRateLimiter(RateLimiter):
    """Sliding-window rate limiter keyed by arbitrary string (typically client IP)."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._call_count = 0

    def _sweep_expired(self, cutoff: float) -> None:
        """Remove keys whose timestamps have all expired."""
        expired_keys = [
            k for k, ts_deque in self._buckets.items() if not ts_deque or ts_deque[-1] <= cutoff
        ]
        for k in expired_keys:
            del self._buckets[k]

    async def is_allowed(self, key: str) -> bool:
        """Return True if the request should be allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            self._call_count += 1
            # Periodically sweep all keys to evict stale entries from
            # clients that have stopped making requests.
            if self._call_count % _CLEANUP_INTERVAL == 0:
                self._sweep_expired(cutoff)

            timestamps = self._buckets.get(key)
            if timestamps is None:
                timestamps = deque()
                self._buckets[key] = timestamps
            # Prune expired entries from the front (timestamps are monotonic)
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) < self._max_requests:
                timestamps.append(now)
                return True

            # Retain only the latest ``max_requests`` attempts so
            # sustained abuse keeps extending the window without letting
            # the bucket grow unbounded.
            timestamps.popleft()
            timestamps.append(now)
            return False


class RedisRateLimiter(RateLimiter):
    """Redis-backed sliding-window rate limiter using sorted sets.

    Each key is stored as a Redis sorted set where members are unique
    request identifiers and scores are wall-clock timestamps. A Lua
    script prunes expired entries, updates the set, and keeps storage
    bounded to the most recent ``max_requests`` attempts.

    Fail-open: if Redis is unreachable during a request, the request is
    allowed and a warning is logged.
    """

    def __init__(
        self,
        *,
        namespace: str,
        max_requests: int,
        window_seconds: float,
        redis_url: str,
    ) -> None:
        self._namespace = namespace
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._client: aioredis.Redis = _get_async_redis(redis_url)

    async def is_allowed(self, key: str) -> bool:
        """Return True if the request should be allowed, False if rate-limited."""
        redis_key = f"ratelimit:{self._namespace}:{key}"
        now = time.time()
        cutoff = now - self._window_seconds
        member = f"{now}:{uuid.uuid4().hex[:8]}"

        try:
            allowed = await cast(
                Awaitable[object],
                self._client.eval(
                    _REDIS_IS_ALLOWED_SCRIPT,
                    1,
                    redis_key,
                    str(cutoff),
                    str(now),
                    member,
                    str(self._max_requests),
                    str(int(self._window_seconds) + 1),
                ),
            )
        except Exception:
            logger.warning(
                "rate_limit.redis.unavailable namespace=%s key=%s",
                self._namespace,
                key,
                exc_info=True,
            )
            return True  # fail-open

        return bool(allowed)


def _redact_url(url: str) -> str:
    """Strip userinfo (credentials) from a Redis URL for safe logging."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.username or parsed.password:
        # Replace user:pass@host with ***@host
        redacted_netloc = f"***@{parsed.hostname}"
        if parsed.port:
            redacted_netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=redacted_netloc))
    return url


def validate_rate_limit_redis(redis_url: str) -> None:
    """Verify Redis is reachable.  Raises ``ConnectionError`` on failure."""
    client = redis_lib.Redis.from_url(redis_url)
    try:
        client.ping()
    except Exception as exc:
        raise ConnectionError(
            f"Redis rate-limit backend configured but unreachable at {_redact_url(redis_url)}: {exc}",
        ) from exc
    finally:
        client.close()


def create_rate_limiter(
    *,
    namespace: str,
    max_requests: int,
    window_seconds: float,
) -> RateLimiter:
    """Create a rate limiter based on the configured backend."""
    from app.core.config import settings

    if settings.rate_limit_backend == RateLimitBackend.REDIS:
        return RedisRateLimiter(
            namespace=namespace,
            max_requests=max_requests,
            window_seconds=window_seconds,
            redis_url=settings.rate_limit_redis_url,
        )
    return InMemoryRateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
    )


# Shared limiter instances for specific endpoints.
# Agent auth: 20 attempts per 60 seconds per IP.
agent_auth_limiter: RateLimiter = create_rate_limiter(
    namespace="agent_auth",
    max_requests=20,
    window_seconds=60.0,
)
# Webhook ingest: 60 requests per 60 seconds per IP.
webhook_ingest_limiter: RateLimiter = create_rate_limiter(
    namespace="webhook_ingest",
    max_requests=60,
    window_seconds=60.0,
)
