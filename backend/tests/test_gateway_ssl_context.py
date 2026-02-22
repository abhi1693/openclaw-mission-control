"""Tests for SSL/TLS configuration in gateway RPC connections."""

from __future__ import annotations

import ssl

from app.services.openclaw.gateway_rpc import GatewayConfig, _create_ssl_context


def test_create_ssl_context_returns_none_for_ws_protocol() -> None:
    """SSL context should be None for non-secure websocket connections."""
    config = GatewayConfig(url="ws://gateway.example:18789/ws")
    ssl_context = _create_ssl_context(config)

    assert ssl_context is None


def test_create_ssl_context_returns_none_for_wss_with_secure_mode() -> None:
    """SSL context should be None for wss:// with default verification (secure mode)."""
    config = GatewayConfig(url="wss://gateway.example:18789/ws", allow_insecure_tls=False)
    ssl_context = _create_ssl_context(config)

    assert ssl_context is None


def test_create_ssl_context_disables_verification_when_allow_insecure_tls_true() -> None:
    """SSL context should disable certificate verification when allow_insecure_tls is True."""
    config = GatewayConfig(url="wss://gateway.example:18789/ws", allow_insecure_tls=True)
    ssl_context = _create_ssl_context(config)

    assert ssl_context is not None
    assert isinstance(ssl_context, ssl.SSLContext)
    assert ssl_context.check_hostname is False
    assert ssl_context.verify_mode == ssl.CERT_NONE


def test_create_ssl_context_respects_localhost_with_insecure_flag() -> None:
    """SSL context for localhost should respect allow_insecure_tls flag."""
    config = GatewayConfig(url="wss://localhost:18789/ws", allow_insecure_tls=True)
    ssl_context = _create_ssl_context(config)

    assert ssl_context is not None
    assert ssl_context.check_hostname is False
    assert ssl_context.verify_mode == ssl.CERT_NONE


def test_create_ssl_context_respects_ip_address_with_insecure_flag() -> None:
    """SSL context for IP addresses should respect allow_insecure_tls flag."""
    config = GatewayConfig(url="wss://192.168.1.100:18789/ws", allow_insecure_tls=True)
    ssl_context = _create_ssl_context(config)

    assert ssl_context is not None
    assert ssl_context.check_hostname is False
    assert ssl_context.verify_mode == ssl.CERT_NONE
