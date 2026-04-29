from __future__ import annotations

import platform

import pytest

import app.services.openclaw.gateway_rpc as gateway_rpc
from app.services.openclaw.gateway_rpc import (
    CONTROL_UI_CLIENT_ID,
    CONTROL_UI_CLIENT_MODE,
    DEFAULT_GATEWAY_CLIENT_ID,
    DEFAULT_GATEWAY_CLIENT_MODE,
    GATEWAY_METHODS,
    GATEWAY_OPERATOR_SCOPES,
    GatewayConfig,
    OpenClawGatewayError,
    _build_connect_params,
    _build_control_ui_origin,
    openclaw_call,
    redact_gateway_error_message,
)


def test_gateway_methods_include_openclaw_426_node_pair_remove() -> None:
    assert "node.pair.remove" in GATEWAY_METHODS


def test_build_connect_params_defaults_to_device_pairing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected_device_payload = {
        "id": "device-id",
        "publicKey": "public-key",
        "signature": "signature",
        "signedAt": 1,
    }

    def _fake_build_device_connect_payload(
        *,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        auth_token: str | None,
        connect_nonce: str | None,
    ) -> dict[str, object]:
        captured["client_id"] = client_id
        captured["client_mode"] = client_mode
        captured["role"] = role
        captured["scopes"] = scopes
        captured["auth_token"] = auth_token
        captured["connect_nonce"] = connect_nonce
        return expected_device_payload

    monkeypatch.setattr(
        gateway_rpc,
        "_build_device_connect_payload",
        _fake_build_device_connect_payload,
    )

    params = _build_connect_params(GatewayConfig(url="ws://gateway.example/ws"))

    assert params["role"] == "operator"
    assert params["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert params["client"]["id"] == DEFAULT_GATEWAY_CLIENT_ID
    assert params["client"]["mode"] == DEFAULT_GATEWAY_CLIENT_MODE
    assert params["client"]["platform"] == platform.system().lower()
    assert params["device"] == expected_device_payload
    assert "auth" not in params
    assert captured["client_id"] == DEFAULT_GATEWAY_CLIENT_ID
    assert captured["client_mode"] == DEFAULT_GATEWAY_CLIENT_MODE
    assert captured["role"] == "operator"
    assert captured["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert captured["auth_token"] is None
    assert captured["connect_nonce"] is None


def test_build_connect_params_uses_control_ui_when_pairing_disabled() -> None:
    params = _build_connect_params(
        GatewayConfig(
            url="ws://gateway.example/ws",
            token="secret-token",
            disable_device_pairing=True,
        ),
    )

    assert params["auth"] == {"token": "secret-token"}
    assert params["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert params["client"]["id"] == CONTROL_UI_CLIENT_ID
    assert params["client"]["mode"] == CONTROL_UI_CLIENT_MODE
    assert params["client"]["platform"] == platform.system().lower()
    assert "device" not in params


def test_build_connect_params_passes_nonce_to_device_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_build_device_connect_payload(
        *,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        auth_token: str | None,
        connect_nonce: str | None,
    ) -> dict[str, object]:
        captured["client_id"] = client_id
        captured["client_mode"] = client_mode
        captured["role"] = role
        captured["scopes"] = scopes
        captured["auth_token"] = auth_token
        captured["connect_nonce"] = connect_nonce
        return {"id": "device-id", "nonce": connect_nonce}

    monkeypatch.setattr(
        gateway_rpc,
        "_build_device_connect_payload",
        _fake_build_device_connect_payload,
    )

    params = _build_connect_params(
        GatewayConfig(url="ws://gateway.example/ws", token="secret-token"),
        connect_nonce="nonce-xyz",
    )

    assert params["auth"] == {"token": "secret-token"}
    assert params["client"]["id"] == DEFAULT_GATEWAY_CLIENT_ID
    assert params["client"]["mode"] == DEFAULT_GATEWAY_CLIENT_MODE
    assert params["device"] == {"id": "device-id", "nonce": "nonce-xyz"}
    assert captured["client_id"] == DEFAULT_GATEWAY_CLIENT_ID
    assert captured["client_mode"] == DEFAULT_GATEWAY_CLIENT_MODE
    assert captured["role"] == "operator"
    assert captured["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert captured["auth_token"] == "secret-token"
    assert captured["connect_nonce"] == "nonce-xyz"


@pytest.mark.parametrize(
    ("gateway_url", "expected_origin"),
    [
        ("ws://gateway.example/ws", "http://gateway.example"),
        ("wss://gateway.example/ws", "https://gateway.example"),
        ("ws://gateway.example:8080/ws", "http://gateway.example:8080"),
        ("wss://gateway.example:8443/ws", "https://gateway.example:8443"),
        ("ws://[::1]:8000/ws", "http://[::1]:8000"),
    ],
)
def test_build_control_ui_origin(gateway_url: str, expected_origin: str) -> None:
    assert _build_control_ui_origin(gateway_url) == expected_origin


@pytest.mark.asyncio
async def test_openclaw_call_uses_single_connect_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def _fake_call_once(
        method: str,
        params: dict[str, object] | None,
        *,
        config: GatewayConfig,
        gateway_url: str,
    ) -> object:
        nonlocal call_count
        del method, params, config, gateway_url
        call_count += 1
        return {"ok": True}

    monkeypatch.setattr(gateway_rpc, "_openclaw_call_once", _fake_call_once)

    payload = await openclaw_call(
        "status",
        config=GatewayConfig(url="ws://gateway.example/ws"),
    )

    assert payload == {"ok": True}
    assert call_count == 1


@pytest.mark.asyncio
async def test_openclaw_call_surfaces_scope_error_without_device_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_call_once(
        method: str,
        params: dict[str, object] | None,
        *,
        config: GatewayConfig,
        gateway_url: str,
    ) -> object:
        del method, params, config, gateway_url
        raise OpenClawGatewayError("missing scope: operator.read")

    monkeypatch.setattr(gateway_rpc, "_openclaw_call_once", _fake_call_once)

    with pytest.raises(OpenClawGatewayError, match="missing scope: operator.read"):
        await openclaw_call(
            "status",
            config=GatewayConfig(url="ws://gateway.example/ws", token="secret-token"),
        )


@pytest.mark.asyncio
async def test_openclaw_call_logs_expected_duplicate_agents_create_as_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_call_once(
        method: str,
        params: dict[str, object] | None,
        *,
        config: GatewayConfig,
        gateway_url: str,
    ) -> object:
        del method, params, config, gateway_url
        raise OpenClawGatewayError("agent already exists")

    seen: list[tuple[str, str]] = []

    def _fake_info(message: str, *args: object) -> None:
        seen.append(("info", message % args))

    def _fake_warning(message: str, *args: object) -> None:
        seen.append(("warning", message % args))

    monkeypatch.setattr(gateway_rpc, "_openclaw_call_once", _fake_call_once)
    monkeypatch.setattr(gateway_rpc.logger, "info", _fake_info)
    monkeypatch.setattr(gateway_rpc.logger, "warning", _fake_warning)

    with pytest.raises(OpenClawGatewayError, match="agent already exists"):
        await openclaw_call(
            "agents.create",
            {"name": "agent-a", "workspace": "/tmp/agent-a"},
            config=GatewayConfig(url="ws://gateway.example/ws"),
        )

    assert any(
        level == "info" and "gateway.rpc.call.gateway_expected_error method=agents.create" in msg
        for level, msg in seen
    )
    assert not any(level == "warning" for level, _msg in seen)


@pytest.mark.asyncio
async def test_openclaw_call_logs_unexpected_gateway_error_as_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_call_once(
        method: str,
        params: dict[str, object] | None,
        *,
        config: GatewayConfig,
        gateway_url: str,
    ) -> object:
        del method, params, config, gateway_url
        raise OpenClawGatewayError("gateway refused update")

    seen: list[tuple[str, str]] = []

    def _fake_info(message: str, *args: object) -> None:
        seen.append(("info", message % args))

    def _fake_warning(message: str, *args: object) -> None:
        seen.append(("warning", message % args))

    monkeypatch.setattr(gateway_rpc, "_openclaw_call_once", _fake_call_once)
    monkeypatch.setattr(gateway_rpc.logger, "info", _fake_info)
    monkeypatch.setattr(gateway_rpc.logger, "warning", _fake_warning)

    with pytest.raises(OpenClawGatewayError, match="gateway refused update"):
        await openclaw_call(
            "agents.create",
            {"name": "agent-a", "workspace": "/tmp/agent-a"},
            config=GatewayConfig(url="ws://gateway.example/ws"),
        )

    assert any(
        level == "warning" and "gateway.rpc.call.gateway_error method=agents.create" in msg
        for level, msg in seen
    )
    assert not any("gateway_expected_error" in msg for _level, msg in seen)


@pytest.mark.asyncio
async def test_openclaw_call_config_patch_builds_operator_connect_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Narrow unit check: when openclaw_call is invoked with method "config.patch",
    # the connect handshake it would perform still builds operator-role params
    # via _build_connect_params. This proves the connect-params builder treats
    # config.patch like any other operator-trusted method — but it does NOT
    # exercise the real provisioning caller. For the real-caller assertion see
    # tests/test_agent_provisioning_utils.py::
    #     test_patch_agent_heartbeats_routes_through_openclaw_call
    captured: dict[str, object] = {}

    async def _fake_call_once(
        method: str,
        params: dict[str, object] | None,
        *,
        config: GatewayConfig,
        gateway_url: str,
    ) -> object:
        del gateway_url
        captured["method"] = method
        captured["params"] = params
        captured["connect_params"] = _build_connect_params(config)
        return {"ok": True}

    monkeypatch.setattr(gateway_rpc, "_openclaw_call_once", _fake_call_once)

    payload = await openclaw_call(
        "config.patch",
        {"agentId": "agent-x", "patch": {"channels": {}}},
        config=GatewayConfig(url="ws://gateway.example/ws"),
    )

    assert payload == {"ok": True}
    assert captured["method"] == "config.patch"
    connect_params = captured["connect_params"]
    assert isinstance(connect_params, dict)
    assert connect_params["role"] == "operator"
    assert connect_params["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert "operator.admin" in connect_params["scopes"]
    assert connect_params["client"]["id"] == DEFAULT_GATEWAY_CLIENT_ID
    assert connect_params["client"]["mode"] == DEFAULT_GATEWAY_CLIENT_MODE
    assert "device" in connect_params


class _FakeConnectContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_openclaw_call_once_does_not_pass_ssl_none_for_wss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_connect(url: str, **kwargs: object) -> _FakeConnectContext:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeConnectContext()

    async def _fake_recv_first(_ws: object) -> None:
        return None

    async def _fake_ensure_connected(
        _ws: object, _first_message: object, _config: GatewayConfig
    ) -> None:
        return None

    async def _fake_send_request(_ws: object, _method: str, _params: object) -> object:
        return {"ok": True}

    monkeypatch.setattr(gateway_rpc.websockets, "connect", _fake_connect)
    monkeypatch.setattr(gateway_rpc, "_recv_first_message_or_none", _fake_recv_first)
    monkeypatch.setattr(gateway_rpc, "_ensure_connected", _fake_ensure_connected)
    monkeypatch.setattr(gateway_rpc, "_send_request", _fake_send_request)

    payload = await gateway_rpc._openclaw_call_once(
        "status",
        None,
        config=GatewayConfig(url="wss://gateway.example/ws", allow_insecure_tls=False),
        gateway_url="wss://gateway.example/ws",
    )

    assert payload == {"ok": True}
    assert captured["url"] == "wss://gateway.example/ws"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "ssl" not in kwargs


@pytest.mark.asyncio
async def test_openclaw_call_once_passes_ssl_context_for_insecure_wss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_connect(url: str, **kwargs: object) -> _FakeConnectContext:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeConnectContext()

    async def _fake_recv_first(_ws: object) -> None:
        return None

    async def _fake_ensure_connected(
        _ws: object, _first_message: object, _config: GatewayConfig
    ) -> None:
        return None

    async def _fake_send_request(_ws: object, _method: str, _params: object) -> object:
        return {"ok": True}

    monkeypatch.setattr(gateway_rpc.websockets, "connect", _fake_connect)
    monkeypatch.setattr(gateway_rpc, "_recv_first_message_or_none", _fake_recv_first)
    monkeypatch.setattr(gateway_rpc, "_ensure_connected", _fake_ensure_connected)
    monkeypatch.setattr(gateway_rpc, "_send_request", _fake_send_request)

    payload = await gateway_rpc._openclaw_call_once(
        "status",
        None,
        config=GatewayConfig(url="wss://gateway.example/ws", allow_insecure_tls=True),
        gateway_url="wss://gateway.example/ws",
    )

    assert payload == {"ok": True}
    assert captured["url"] == "wss://gateway.example/ws"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("ssl") is not None


# --------------------------------------------------------------------
# redact_gateway_error_message (Part D.3 defence-in-depth)
#
# ``OpenClawGatewayError`` wraps gateway + transport errors whose
# ``__str__`` may embed the gateway URL (with its ``?token=`` query)
# or token-bearing headers. Errors flow into operator-facing Blocker
# citations via the stale-agent filer, so the redactor must scrub
# token substrings before anything persists.
# --------------------------------------------------------------------


def test_redact_strips_token_query_param() -> None:
    msg = (
        "ConnectionError: failed to reach "
        "wss://gateway.local/ws?token=super-secret-shared-key"
    )
    cleaned = redact_gateway_error_message(msg)
    assert "super-secret-shared-key" not in cleaned
    assert "token=<redacted>" in cleaned
    # Host + path preserved — operators still need the signal.
    assert "gateway.local/ws" in cleaned


def test_redact_handles_mixed_case_and_aliases() -> None:
    msg = "GET /foo?ACCESS_TOKEN=abc123&token=xyz789 returned 401"
    cleaned = redact_gateway_error_message(msg)
    assert "abc123" not in cleaned
    assert "xyz789" not in cleaned
    assert "=<redacted>" in cleaned


def test_redact_scrubs_bare_bearer_header() -> None:
    msg = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig failed"
    cleaned = redact_gateway_error_message(msg)
    # Both the bearer kv and the JWT shape get caught — the result
    # must contain neither the original token nor the JWT payload.
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "<redacted" in cleaned


def test_redact_scrubs_jwt_shape_outside_query() -> None:
    msg = "gateway returned 403 for eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.Xb2r1WcUQh"
    cleaned = redact_gateway_error_message(msg)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in cleaned
    assert "<redacted-jwt>" in cleaned


def test_redact_leaves_token_free_messages_intact() -> None:
    msg = "Stale agent session: agent `frontend-dev` not found in config"
    assert redact_gateway_error_message(msg) == msg


def test_redact_preserves_request_id() -> None:
    """4.20 gateway errors include request_ids for operator correlation
    — those must survive the redactor."""

    msg = "PAIRING_REQUIRED: scope upgrade needed (request_id=req-abc-123)"
    cleaned = redact_gateway_error_message(msg)
    assert "request_id=req-abc-123" in cleaned
