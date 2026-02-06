from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^(?P<num>[1-9]\\d*)\\s*(?P<unit>[smhdw])$", flags=re.IGNORECASE)

_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
    "w": 60 * 60 * 24 * 7,
}


def normalize_every(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "")
    if not normalized:
        raise ValueError("schedule is required")
    return normalized


def parse_every_to_seconds(value: str) -> int:
    normalized = normalize_every(value)
    match = _DURATION_RE.match(normalized)
    if not match:
        raise ValueError('Invalid schedule. Expected format like "10m", "1h", "2d", "1w".')
    num = int(match.group("num"))
    unit = match.group("unit").lower()
    seconds = num * _MULTIPLIERS[unit]
    if seconds <= 0:
        raise ValueError("Schedule must be greater than 0.")
    # Prevent accidental absurd schedules (e.g. 999999999d).
    if seconds > 60 * 60 * 24 * 365 * 10:
        raise ValueError("Schedule is too large (max 10 years).")
    return seconds

