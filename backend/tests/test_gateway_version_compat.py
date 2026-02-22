# ruff: noqa: S101
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.services.openclaw.admin_service as admin_service
import app.services.openclaw.gateway_compat as gateway_compat
import app.services.openclaw.session_service as session_service
from app.schemas.gateway_api import GatewayResolveQuery
from app.services.openclaw.admin_service import GatewayAdminLifecycleService
from app.services.openclaw.gateway_compat import GatewayVersionCheckResult
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError
from app.services.openclaw.session_service import GatewaySessionService


def test_extract_gateway_version_prefers_primary_path() -> None:
    payload = {
        "gateway": {"version": "2026.2.1"},
        "protocolVersion": 3,
        "meta": {"version": "2026.1.30"},
    }

    assert gateway_compat.extract_gateway_version(payload) == "2026.2.1"


def test_evaluate_gateway_version_detects_old_runtime() -> None:
    result = gateway_compat.evaluate_gateway_version(
        current_version="2025.12.1",
        minimum_version="2026.1.30",
    )

    assert result.compatible is False
    assert result.minimum_version == "2026.1.30"
    assert "Minimum supported version is 2026.1.30" in (result.message or "")


def test_parse_version_parts_handles_build_suffix() -> None:
    """Test that version parsing works with build suffixes like -2."""
    result = gateway_compat._parse_version_parts("2026.2.21-2")
    assert result == (2026, 2, 21)


def test_parse_version_parts_handles_zero_padded_month() -> None:
    """Test that version parsing works with zero-padded months."""
    result = gateway_compat._parse_version_parts("2026.02.21-2")
    assert result == (2026, 2, 21)


def test_parse_version_parts_handles_non_zero_padded_day() -> None:
    """Test that version parsing works with non-zero-padded days."""
    result = gateway_compat._parse_version_parts("2026.2.9")
    assert result == (2026, 2, 9)


def test_parse_version_parts_handles_zero_padded_day() -> None:
    """Test that version parsing works with zero-padded days."""
    result = gateway_compat._parse_version_parts("2026.02.09")
    assert result == (2026, 2, 9)


def test_evaluate_gateway_version_accepts_non_zero_padded_with_suffix() -> None:
    """Test the exact scenario from the issue: non-zero-padded month with build suffix."""
    result = gateway_compat.evaluate_gateway_version(
        current_version="2026.2.21-2",
        minimum_version="2026.02.9",
    )

    assert result.compatible is True
    assert result.current_version == "2026.2.21-2"
    assert result.minimum_version == "2026.02.9"


def test_evaluate_gateway_version_accepts_zero_padded_with_suffix() -> None:
    """Test that zero-padded version with suffix also works."""
    result = gateway_compat.evaluate_gateway_version(
        current_version="2026.02.21-2",
        minimum_version="2026.02.9",
    )

    assert result.compatible is True
    assert result.current_version == "2026.02.21-2"
    assert result.minimum_version == "2026.02.9"


def test_evaluate_gateway_version_compares_non_zero_padded_correctly() -> None:
    """Test that non-zero-padded versions are compared correctly."""
    # 2026.2.21 should be greater than 2026.2.9
    result = gateway_compat.evaluate_gateway_version(
        current_version="2026.2.21",
        minimum_version="2026.2.9",
    )

    assert result.compatible is True

    # 2026.2.5 should be less than 2026.2.9
    result = gateway_compat.evaluate_gateway_version(
        current_version="2026.2.5",
        minimum_version="2026.2.9",
    )

    assert result.compatible is False


@pytest.mark.asyncio
async def test_check_gateway_runtime_compatibility_prefers_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        calls.append(method)
        if method == "config.schema":
            return {"version": "2026.2.13"}
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_runtime_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert calls == ["config.schema"]
    assert result.compatible is True
    assert result.current_version == "2026.2.13"


@pytest.mark.asyncio
async def test_check_gateway_runtime_compatibility_falls_back_to_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        calls.append(method)
        if method == "config.schema":
            raise OpenClawGatewayError("unknown method")
        if method == "status":
            raise OpenClawGatewayError("unknown method")
        return {"version": "2026.2.0"}

    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_runtime_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert calls == ["config.schema", "status", "health"]
    assert result.compatible is True
    assert result.current_version == "2026.2.0"


@pytest.mark.asyncio
async def test_check_gateway_runtime_compatibility_uses_health_when_status_has_no_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        calls.append(method)
        if method == "config.schema":
            return {"schema": {"title": "Gateway schema"}}
        if method == "status":
            return {"uptime": 1234}
        return {"version": "2026.2.0"}

    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_runtime_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert calls == ["config.schema", "status", "health"]
    assert result.compatible is True
    assert result.current_version == "2026.2.0"


@pytest.mark.asyncio
async def test_admin_service_rejects_incompatible_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version="2026.1.30",
            current_version="2026.1.0",
            message="Gateway version 2026.1.0 is not supported.",
        )

    monkeypatch.setattr(admin_service, "check_gateway_runtime_compatibility", _fake_check)

    service = GatewayAdminLifecycleService(session=object())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await service.assert_gateway_runtime_compatible(url="ws://gateway.example/ws", token=None)

    assert exc_info.value.status_code == 422
    assert "not supported" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_admin_service_maps_gateway_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        raise OpenClawGatewayError("connection refused")

    monkeypatch.setattr(admin_service, "check_gateway_runtime_compatibility", _fake_check)

    service = GatewayAdminLifecycleService(session=object())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await service.assert_gateway_runtime_compatible(url="ws://gateway.example/ws", token=None)

    assert exc_info.value.status_code == 502
    assert "compatibility check failed" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_gateway_status_reports_incompatible_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        return GatewayVersionCheckResult(
            compatible=False,
            minimum_version="2026.1.30",
            current_version="2026.1.0",
            message="Gateway version 2026.1.0 is not supported.",
        )

    monkeypatch.setattr(session_service, "check_gateway_runtime_compatibility", _fake_check)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    response = await service.get_status(
        params=GatewayResolveQuery(gateway_url="ws://gateway.example/ws"),
        organization_id=uuid4(),
        user=None,
    )

    assert response.connected is False
    assert response.error == "Gateway version 2026.1.0 is not supported."


@pytest.mark.asyncio
async def test_gateway_status_returns_sessions_when_version_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        return GatewayVersionCheckResult(
            compatible=True,
            minimum_version="2026.1.30",
            current_version="2026.2.0",
            message=None,
        )

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        assert method == "sessions.list"
        return {"sessions": [{"key": "agent:main"}]}

    monkeypatch.setattr(session_service, "check_gateway_runtime_compatibility", _fake_check)
    monkeypatch.setattr(session_service, "openclaw_call", _fake_openclaw_call)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    response = await service.get_status(
        params=GatewayResolveQuery(gateway_url="ws://gateway.example/ws"),
        organization_id=uuid4(),
        user=None,
    )

    assert response.connected is True
    assert response.sessions_count == 1
