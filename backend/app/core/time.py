"""Time-related helpers shared across backend modules."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return a naive UTC datetime without using deprecated datetime.utcnow()."""
    # Keep naive UTC values for compatibility with existing DB schema/queries.
    return datetime.now(UTC).replace(tzinfo=None)
