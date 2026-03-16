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


def test_extract_connect_server_version_uses_server_version_as_source_of_truth() -> None:
    payload = {
        "version": "dev",
        "runtime": {"version": "2026.1.0"},
        "server": {"version": "2026.2.21-2"},
    }

    assert gateway_compat.extract_connect_server_version(payload) == "2026.2.21-2"


def test_extract_connect_server_version_returns_none_when_server_version_missing() -> None:
    payload = {
        "version": "2026.2.21-2",
        "runtime": {"version": "2026.2.21-2"},
    }

    assert gateway_compat.extract_connect_server_version(payload) is None


def test_extract_config_last_touched_version_reads_config_meta_last_touched_version() -> None:
    payload = {
        "config": {
            "meta": {"lastTouchedVersion": "2026.2.9"},
            "wizard": {"lastRunVersion": "2026.2.8"},
        },
        "parsed": {"meta": {"lastTouchedVersion": "2026.2.7"}},
    }

    assert gateway_compat.extract_config_last_touched_version(payload) == "2026.2.9"


def test_extract_config_last_touched_version_returns_none_without_config_meta_last_touched_version() -> (
    None
):
    payload = {
        "config": {"wizard": {"lastRunVersion": "2026.2.9"}},
    }

    assert gateway_compat.extract_config_last_touched_version(payload) is None


@pytest.mark.parametrize(
    ("current_version", "minimum_version", "expected_compatible"),
    [
        ("2026.2.21", "2026.2.21", True),
        ("2026.02.20", "2026.2.20", True),
        ("2026.2.22", "2026.2.21", True),
        ("2026.2.21-2", "2026.2.21-1", True),
        ("2026.2.21-1", "2026.2.21-2", False),
        ("2026.2.20", "2026.2.21", False),
    ],
)
def test_evaluate_gateway_version_compares_calver(
    *,
    current_version: str,
    minimum_version: str,
    expected_compatible: bool,
) -> None:
    result = gateway_compat.evaluate_gateway_version(
        current_version=current_version,
        minimum_version=minimum_version,
    )

    assert result.compatible is expected_compatible
    assert result.current_version == current_version
    assert result.minimum_version == minimum_version


@pytest.mark.parametrize("invalid_current", ["dev", "latest", "2026.13.1", "2026.2.0-beta"])
def test_evaluate_gateway_version_rejects_non_calver_current(invalid_current: str) -> None:
    result = gateway_compat.evaluate_gateway_version(
        current_version=invalid_current,
        minimum_version="2026.1.30",
    )

    assert result.compatible is False
    assert result.current_version == invalid_current
    assert "unsupported version format" in (result.message or "").lower()


def test_evaluate_gateway_version_rejects_non_calver_minimum_version() -> None:
    result = gateway_compat.evaluate_gateway_version(
        current_version="2026.2.21",
        minimum_version="1.2.3",
    )

    assert result.compatible is False
    assert result.minimum_version == "1.2.3"
    assert "expected calver" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_check_gateway_version_compatibility_uses_connect_server_version_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_connect_metadata(*, config: GatewayConfig) -> object | None:
        _ = config
        return {
            "version": "dev",
            "runtime": {"version": "2026.1.0"},
            "server": {"version": "2026.2.13"},
        }

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (method, params, config)
        raise AssertionError("config.get fallback should not run for valid connect version")

    monkeypatch.setattr(gateway_compat, "openclaw_connect_metadata", _fake_connect_metadata)
    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_version_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert result.compatible is True
    assert result.current_version == "2026.2.13"


@pytest.mark.asyncio
async def test_check_gateway_version_compatibility_fails_without_server_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_connect_metadata(*, config: GatewayConfig) -> object | None:
        _ = config
        return {"runtime": {"version": "2026.2.13"}}

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        assert method == "config.get"
        return {"config": {}}

    monkeypatch.setattr(gateway_compat, "openclaw_connect_metadata", _fake_connect_metadata)
    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_version_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert result.compatible is False
    assert result.current_version is None
    assert "unable to determine gateway version" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_check_gateway_version_compatibility_uses_config_get_fallback_when_connect_is_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_connect_metadata(*, config: GatewayConfig) -> object | None:
        _ = config
        return {"server": {"version": "dev"}}

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (params, config)
        assert method == "config.get"
        return {"config": {"meta": {"lastTouchedVersion": "2026.2.9"}}}

    monkeypatch.setattr(gateway_compat, "openclaw_connect_metadata", _fake_connect_metadata)
    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_version_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert result.compatible is True
    assert result.current_version == "2026.2.9"


@pytest.mark.asyncio
async def test_check_gateway_version_compatibility_rejects_non_calver_server_version_when_fallback_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_connect_metadata(*, config: GatewayConfig) -> object | None:
        _ = config
        return {"server": {"version": "dev"}}

    async def _fake_openclaw_call(method: str, params: object = None, *, config: object) -> object:
        _ = (method, params, config)
        raise OpenClawGatewayError("method unavailable")

    monkeypatch.setattr(gateway_compat, "openclaw_connect_metadata", _fake_connect_metadata)
    monkeypatch.setattr(gateway_compat, "openclaw_call", _fake_openclaw_call)

    result = await gateway_compat.check_gateway_version_compatibility(
        GatewayConfig(url="ws://gateway.example/ws"),
        minimum_version="2026.1.30",
    )

    assert result.compatible is False
    assert result.current_version == "dev"
    assert "unsupported version format" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_check_gateway_version_compatibility_propagates_connect_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_connect_metadata(*, config: GatewayConfig) -> object | None:
        _ = config
        raise OpenClawGatewayError("connection refused")

    monkeypatch.setattr(gateway_compat, "openclaw_connect_metadata", _fake_connect_metadata)

    with pytest.raises(OpenClawGatewayError, match="connection refused"):
        await gateway_compat.check_gateway_version_compatibility(
            GatewayConfig(url="ws://gateway.example/ws"),
            minimum_version="2026.1.30",
        )


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

    monkeypatch.setattr(admin_service, "check_gateway_version_compatibility", _fake_check)

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

    monkeypatch.setattr(admin_service, "check_gateway_version_compatibility", _fake_check)

    service = GatewayAdminLifecycleService(session=object())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await service.assert_gateway_runtime_compatible(url="ws://gateway.example/ws", token=None)

    assert exc_info.value.status_code == 502
    assert "compatibility check failed" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_admin_service_maps_gateway_scope_errors_with_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        raise OpenClawGatewayError("missing scope: operator.read")

    monkeypatch.setattr(admin_service, "check_gateway_version_compatibility", _fake_check)

    service = GatewayAdminLifecycleService(session=object())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await service.assert_gateway_runtime_compatible(url="ws://gateway.example/ws", token=None)

    assert exc_info.value.status_code == 502
    assert "missing required scope `operator.read`" in str(exc_info.value.detail)


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

    monkeypatch.setattr(session_service, "check_gateway_version_compatibility", _fake_check)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    response = await service.get_status(
        params=GatewayResolveQuery(gateway_url="ws://gateway.example/ws"),
        organization_id=uuid4(),
        user=None,
    )

    assert response.connected is False
    assert response.error == "Gateway version 2026.1.0 is not supported."


@pytest.mark.asyncio
async def test_gateway_status_surfaces_scope_error_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(config: GatewayConfig, *, minimum_version: str | None = None) -> object:
        _ = (config, minimum_version)
        raise OpenClawGatewayError("missing scope: operator.read")

    monkeypatch.setattr(session_service, "check_gateway_version_compatibility", _fake_check)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    response = await service.get_status(
        params=GatewayResolveQuery(gateway_url="ws://gateway.example/ws"),
        organization_id=uuid4(),
        user=None,
    )

    assert response.connected is False
    assert response.error is not None
    assert "missing required scope `operator.read`" in response.error


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

    monkeypatch.setattr(session_service, "check_gateway_version_compatibility", _fake_check)
    monkeypatch.setattr(session_service, "openclaw_call", _fake_openclaw_call)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    response = await service.get_status(
        params=GatewayResolveQuery(gateway_url="ws://gateway.example/ws"),
        organization_id=uuid4(),
        user=None,
    )

    assert response.connected is True
    assert response.sessions_count == 1
