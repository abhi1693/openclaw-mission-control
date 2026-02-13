from __future__ import annotations

from app.services.openclaw.gateway_rpc import (
    GATEWAY_OPERATOR_SCOPES,
    GatewayConfig,
    _build_connect_params,
)


def test_build_connect_params_sets_explicit_operator_role_and_scopes() -> None:
    params = _build_connect_params(GatewayConfig(url="ws://gateway.example/ws"))

    assert params["role"] == "operator"
    assert params["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
    assert "auth" not in params


def test_build_connect_params_includes_auth_token_when_provided() -> None:
    params = _build_connect_params(
        GatewayConfig(url="ws://gateway.example/ws", token="secret-token"),
    )

    assert params["auth"] == {"token": "secret-token"}
    assert params["scopes"] == list(GATEWAY_OPERATOR_SCOPES)
