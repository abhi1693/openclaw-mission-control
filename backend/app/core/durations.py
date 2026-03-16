"""Utilities for parsing human-readable duration schedule strings."""

from __future__ import annotations

import re

_DURATION_RE = re.compile(
    r"^(?P<num>[1-9]\\d*)\\s*(?P<unit>[smhdw])$",
    flags=re.IGNORECASE,
)

_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
    "w": 60 * 60 * 24 * 7,
}
_MAX_SCHEDULE_SECONDS = 60 * 60 * 24 * 365 * 10

_ERR_SCHEDULE_REQUIRED = "schedule is required"
_ERR_SCHEDULE_INVALID = 'Invalid schedule. Expected format like "10m", "1h", "2d", "1w".'
_ERR_SCHEDULE_NONPOSITIVE = "Schedule must be greater than 0."
_ERR_SCHEDULE_TOO_LARGE = "Schedule is too large (max 10 years)."


def normalize_every(value: str) -> str:
    """Normalize schedule string to lower-case compact unit form."""
    normalized = value.strip().lower().replace(" ", "")
    if not normalized:
        raise ValueError(_ERR_SCHEDULE_REQUIRED)
    return normalized


def parse_every_to_seconds(value: str) -> int:
    """Parse compact schedule syntax into a number of seconds."""
    normalized = normalize_every(value)
    match = _DURATION_RE.match(normalized)
    if not match:
        raise ValueError(_ERR_SCHEDULE_INVALID)
    num = int(match.group("num"))
    unit = match.group("unit").lower()
    seconds = num * _MULTIPLIERS[unit]
    if seconds <= 0:
        raise ValueError(_ERR_SCHEDULE_NONPOSITIVE)
    # Prevent accidental absurd schedules (e.g. 999999999d).
    if seconds > _MAX_SCHEDULE_SECONDS:
        raise ValueError(_ERR_SCHEDULE_TOO_LARGE)
    return seconds
