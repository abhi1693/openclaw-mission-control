"""Gateway runtime version compatibility checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger
from app.services.openclaw.gateway_rpc import (
    GatewayConfig,
    OpenClawGatewayError,
    openclaw_call,
    openclaw_connect_metadata,
)

_CALVER_PATTERN = re.compile(
    r"^v?(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})(?:-(?P<rev>\d+))?$",
    re.IGNORECASE,
)
_CONNECT_VERSION_PATH: tuple[str, ...] = ("server", "version")
_CONFIG_VERSION_PATH: tuple[str, ...] = ("config", "meta", "lastTouchedVersion")
logger = get_logger(__name__)


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
    match = _CALVER_PATTERN.match(value.strip())
    if match is None:
        return None
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    revision = int(match.group("rev") or 0)
    if month < 1 or month > 12:
        return None
    if day < 1 or day > 31:
        return None
    return (year, month, day, revision)


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


def extract_connect_server_version(payload: object) -> str | None:
    """Extract the canonical runtime version from connect metadata."""
    return _coerce_version_string(_value_at_path(payload, _CONNECT_VERSION_PATH))


def extract_config_last_touched_version(payload: object) -> str | None:
    """Extract a runtime version hint from config.get payload."""
    return _coerce_version_string(_value_at_path(payload, _CONFIG_VERSION_PATH))


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
            f"Expected CalVer 'YYYY.M.D' or 'YYYY.M.D-REV', got '{min_version}'."
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
                f"Minimum supported version is {min_version}."
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


async def check_gateway_version_compatibility(
    config: GatewayConfig,
    *,
    minimum_version: str | None = None,
) -> GatewayVersionCheckResult:
    """Evaluate gateway compatibility using connect metadata with config fallback."""
    connect_payload = await openclaw_connect_metadata(config=config)
    current_version = extract_connect_server_version(connect_payload)
    if current_version is None or _parse_version_parts(current_version) is None:
        try:
            config_payload = await openclaw_call("config.get", config=config)
        except OpenClawGatewayError as exc:
            logger.debug(
                "gateway.compat.config_get_fallback_unavailable reason=%s",
                str(exc),
            )
        else:
            fallback_version = extract_config_last_touched_version(config_payload)
            if fallback_version is not None:
                current_version = fallback_version
    return evaluate_gateway_version(
        current_version=current_version,
        minimum_version=minimum_version,
    )
