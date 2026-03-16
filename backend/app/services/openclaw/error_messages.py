"""Normalization helpers for user-facing OpenClaw gateway errors."""

from __future__ import annotations

import re

_MISSING_SCOPE_PATTERN = re.compile(
    r"missing\s+scope\s*:\s*(?P<scope>[A-Za-z0-9._:-]+)",
    re.IGNORECASE,
)


def normalize_gateway_error_message(message: str) -> str:
    """Return a user-friendly message for common gateway auth failures."""
    raw_message = message.strip()
    if not raw_message:
        return "Gateway authentication failed. Verify gateway token and operator scopes."

    missing_scope = _MISSING_SCOPE_PATTERN.search(raw_message)
    if missing_scope is not None:
        scope = missing_scope.group("scope")
        return (
            f"Gateway token is missing required scope `{scope}`. "
            "Update the gateway token scopes and retry."
        )

    lowered = raw_message.lower()
    if "unauthorized" in lowered or "forbidden" in lowered:
        return "Gateway authentication failed. Verify gateway token and operator scopes."

    return raw_message
