# ruff: noqa: S101
from __future__ import annotations

from uuid import uuid4

import pytest

import app.services.openclaw.session_service as session_service
from app.models.gateways import Gateway
from app.schemas.gateway_api import GatewayResolveQuery
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    optional_gateway_client_config,
)
from app.services.openclaw.session_service import GatewaySessionService


def _gateway(
    *,
    disable_device_pairing: bool,
    allow_insecure_tls: bool = False,
    url: str = "ws://gateway.example:18789/ws",
    token: str | None = " secret-token ",
) -> Gateway:
    return Gateway(
        id=uuid4(),
        organization_id=uuid4(),
        name="Primary gateway",
        url=url,
        token=token,
        workspace_root="~/.openclaw",
        disable_device_pairing=disable_device_pairing,
        allow_insecure_tls=allow_insecure_tls,
    )


def test_gateway_client_config_maps_disable_device_pairing() -> None:
    config = gateway_client_config(_gateway(disable_device_pairing=True))

    assert config.url == "ws://gateway.example:18789/ws"
    assert config.token == "secret-token"
    assert config.disable_device_pairing is True


def test_optional_gateway_client_config_maps_disable_device_pairing() -> None:
    config = optional_gateway_client_config(_gateway(disable_device_pairing=False))

    assert config is not None
    assert config.disable_device_pairing is False


def test_gateway_client_config_maps_allow_insecure_tls() -> None:
    config = gateway_client_config(
        _gateway(disable_device_pairing=False, allow_insecure_tls=True),
    )

    assert config.allow_insecure_tls is True


def test_optional_gateway_client_config_returns_none_for_missing_or_blank_url() -> None:
    assert optional_gateway_client_config(None) is None
    assert (
        optional_gateway_client_config(
            _gateway(disable_device_pairing=False, url="   "),
        )
        is None
    )


def test_to_resolve_query_keeps_gateway_disable_device_pairing_value() -> None:
    resolved = GatewaySessionService.to_resolve_query(
        board_id=None,
        gateway_url="ws://gateway.example:18789/ws",
        gateway_token="secret-token",
        gateway_disable_device_pairing=True,
    )

    assert resolved.gateway_disable_device_pairing is True


def test_to_resolve_query_keeps_gateway_allow_insecure_tls_value() -> None:
    resolved = GatewaySessionService.to_resolve_query(
        board_id=None,
        gateway_url="wss://gateway.example:18789/ws",
        gateway_token="secret-token",
        gateway_allow_insecure_tls=True,
    )

    assert resolved.gateway_allow_insecure_tls is True


@pytest.mark.asyncio
async def test_resolve_gateway_keeps_gateway_allow_insecure_tls_for_direct_url() -> None:
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    _, config, _ = await service.resolve_gateway(
        GatewayResolveQuery(
            gateway_url="wss://gateway.example:18789/ws",
            gateway_allow_insecure_tls=True,
        ),
        user=None,
    )

    assert config.allow_insecure_tls is True


class _FakeGatewayQuery:
    def __init__(self, gateway: Gateway | None) -> None:
        self._gateway = gateway
        self.filters: list[dict[str, object]] = []

    def filter_by(self, **kwargs: object) -> _FakeGatewayQuery:
        self.filters.append(kwargs)
        return self

    async def first(self, _session: object) -> Gateway | None:
        return self._gateway


class _FakeAsyncSession:
    async def exec(
        self, *_args: object, **_kwargs: object
    ) -> None:  # pragma: no cover - guard only
        return None


@pytest.mark.asyncio
async def test_resolve_gateway_uses_saved_gateway_settings_when_direct_flags_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway(
        disable_device_pairing=True,
        allow_insecure_tls=True,
        url="wss://gateway.example:18789/ws",
        token=" db-token ",
    )
    fake_query = _FakeGatewayQuery(gateway)
    monkeypatch.setattr(session_service.Gateway, "objects", fake_query)

    service = GatewaySessionService(session=_FakeAsyncSession())  # type: ignore[arg-type]
    _, config, _ = await service.resolve_gateway(
        GatewayResolveQuery(gateway_url=gateway.url),
        user=None,
        organization_id=gateway.organization_id,
    )

    assert config.token is None
    assert config.allow_insecure_tls is True
    assert config.disable_device_pairing is True
    assert fake_query.filters == [
        {"url": gateway.url},
        {"organization_id": gateway.organization_id},
    ]


@pytest.mark.asyncio
async def test_resolve_gateway_prefers_explicit_direct_flags_over_saved_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway(
        disable_device_pairing=True,
        allow_insecure_tls=True,
        url="wss://gateway.example:18789/ws",
        token="db-token",
    )
    fake_query = _FakeGatewayQuery(gateway)
    monkeypatch.setattr(session_service.Gateway, "objects", fake_query)

    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    _, config, _ = await service.resolve_gateway(
        GatewayResolveQuery(
            gateway_url=gateway.url,
            gateway_token="explicit-token",
            gateway_allow_insecure_tls=False,
            gateway_disable_device_pairing=False,
        ),
        user=None,
        organization_id=gateway.organization_id,
    )

    assert config.token == "explicit-token"
    assert config.allow_insecure_tls is False
    assert config.disable_device_pairing is False
