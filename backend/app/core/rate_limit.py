"""Simple in-memory token-bucket rate limiter for abuse prevention.

This provides per-IP rate limiting without external dependencies.
For multi-process or distributed deployments, a Redis-based limiter
should be used instead.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class InMemoryRateLimiter:
    """Token-bucket rate limiter keyed by arbitrary string (typically client IP)."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True if the request should be allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            timestamps = self._buckets[key]
            # Prune expired entries
            self._buckets[key] = [ts for ts in timestamps if ts > cutoff]
            if len(self._buckets[key]) >= self._max_requests:
                return False
            self._buckets[key].append(now)
            return True


# Shared limiter instances for specific endpoints.
# Agent auth: 20 attempts per 60 seconds per IP.
agent_auth_limiter = InMemoryRateLimiter(max_requests=20, window_seconds=60.0)
# Webhook ingest: 60 requests per 60 seconds per IP.
webhook_ingest_limiter = InMemoryRateLimiter(max_requests=60, window_seconds=60.0)
