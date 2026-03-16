"""Rate-limit backend selection enum."""

from __future__ import annotations

from enum import Enum


class RateLimitBackend(str, Enum):
    """Supported rate-limiting backends."""

    MEMORY = "memory"
    REDIS = "redis"
