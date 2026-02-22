"""Gateway runtime version compatibility checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError, openclaw_call

_VERSION_PATTERN = re.compile(r"(?i)v?(?P<version>\d+(?:\.\d+)+)")
_PRIMARY_VERSION_PATHS: tuple[tuple[str, ...], ...] = (
    ("version",),
    ("gatewayVersion",),
    ("appVersion",),
    ("buildVersion",),
    ("gateway", "version"),
    ("app", "version"),
    ("server", "version"),
    ("runtime", "version"),
    ("meta", "version"),
    ("build", "version"),
    ("info", "version"),
)


@dataclass(frozen=True, slots=True)
class GatewayVersionCheckResult:
    """Compatibility verdict for a gateway runtime version."""

    compatible: bool
    minimum_version: str
    current_version: str | None
    message: str | None = None


def _normalized_minimum_version() -> str:
    raw = (settings.gateway_min_version or "").strip()
    return raw or "2026.1.30"


def _parse_version_parts(value: str) -> tuple[int, ...] | None:
    """Parse version string into tuple of integers.

    Supports various version formats including:
    - Zero-padded: "2026.02.21-2" -> (2026, 2, 21)
    - Non-zero-padded: "2026.2.21-2" -> (2026, 2, 21)
    - With/without build suffix: "2026.2.9" or "2026.2.9-2"
    - With/without 'v' prefix: "v2026.2.9" or "2026.2.9"

    Build suffixes (e.g., "-2") are ignored during parsing.
    """
    match = _VERSION_PATTERN.search(value.strip())
    if match is None:
        return None
    numeric = match.group("version")
    return tuple(int(part) for part in numeric.split("."))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    left_padded = left + (0,) * (width - len(left))
    right_padded = right + (0,) * (width - len(right))
    if left_padded < right_padded:
        return -1
    if left_padded > right_padded:
        return 1
    return 0


def _value_at_path(payload: object, path: tuple[str, ...]) -> object | None:
    current = payload
    for segment in path:
        if not isinstance(current, dict):
            return None
        if segment not in current:
            return None
        current = current[segment]
    return current


def _coerce_version_string(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _iter_fallback_version_values(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    stack: list[dict[str, Any]] = [payload]
    discovered: list[str] = []
    while stack:
        node = stack.pop()
        for key, value in node.items():
            if isinstance(value, dict):
                stack.append(value)
            key_lower = key.lower()
            if "version" not in key_lower or "protocol" in key_lower:
                continue
            candidate = _coerce_version_string(value)
            if candidate is not None:
                discovered.append(candidate)
    return discovered


def extract_gateway_version(payload: object) -> str | None:
    """Extract a gateway runtime version string from status/health payloads."""
    for path in _PRIMARY_VERSION_PATHS:
        candidate = _coerce_version_string(_value_at_path(payload, path))
        if candidate is not None:
            return candidate

    for candidate in _iter_fallback_version_values(payload):
        if _parse_version_parts(candidate) is not None:
            return candidate
    return None


def evaluate_gateway_version(
    *,
    current_version: str | None,
    minimum_version: str | None = None,
) -> GatewayVersionCheckResult:
    """Return compatibility result for the reported gateway version."""
    min_version = (minimum_version or _normalized_minimum_version()).strip()
    min_parts = _parse_version_parts(min_version)
    if min_parts is None:
        msg = (
            "Server configuration error: GATEWAY_MIN_VERSION is invalid. "
            f"Expected a dotted numeric version, got '{min_version}'."
        )
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version=min_version,
            current_version=current_version,
            message=msg,
        )

    if current_version is None:
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version=min_version,
            current_version=None,
            message=(
                "Unable to determine gateway version from runtime metadata. "
                "The gateway's config.schema, status, or health endpoints did not "
                "return version information in any recognized format. "
                f"Minimum supported version is {min_version}. "
                "Please ensure your gateway is up to date and properly configured."
            ),
        )

    current_parts = _parse_version_parts(current_version)
    if current_parts is None:
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version=min_version,
            current_version=current_version,
            message=(
                f"Gateway reported an unsupported version format '{current_version}'. "
                f"Minimum supported version is {min_version}."
            ),
        )

    if _compare_versions(current_parts, min_parts) < 0:
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version=min_version,
            current_version=current_version,
            message=(
                f"Gateway version {current_version} is not supported. "
                f"Minimum supported version is {min_version}."
            ),
        )

    return GatewayVersionCheckResult(
        compatible=True,
        minimum_version=min_version,
        current_version=current_version,
    )


async def _fetch_runtime_metadata(config: GatewayConfig) -> object:
    last_error: OpenClawGatewayError | None = None
    for method in ("status", "health"):
        try:
            return await openclaw_call(method, config=config)
        except OpenClawGatewayError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return {}


async def _fetch_schema_metadata(config: GatewayConfig) -> object | None:
    try:
        return await openclaw_call("config.schema", config=config)
    except OpenClawGatewayError:
        return None


async def check_gateway_runtime_compatibility(
    config: GatewayConfig,
    *,
    minimum_version: str | None = None,
) -> GatewayVersionCheckResult:
    """Fetch runtime metadata and evaluate gateway version compatibility."""
    schema_payload = await _fetch_schema_metadata(config)
    current_version = extract_gateway_version(schema_payload)
    if current_version is not None:
        return evaluate_gateway_version(
            current_version=current_version,
            minimum_version=minimum_version,
        )

    payload = await _fetch_runtime_metadata(config)
    current_version = extract_gateway_version(payload)
    if current_version is None:
        try:
            health_payload = await openclaw_call("health", config=config)
        except OpenClawGatewayError:
            health_payload = None
        if health_payload is not None:
            current_version = extract_gateway_version(health_payload)
    return evaluate_gateway_version(
        current_version=current_version,
        minimum_version=minimum_version,
    )
