"""Tests for trusted client-IP extraction."""

from __future__ import annotations

from unittest.mock import patch

from app.core.client_ip import (
    _extract_from_forwarded,
    _extract_from_x_forwarded_for,
    _parse_trusted_networks,
    _strip_port,
    get_client_ip,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, peer_ip: str, headers: dict[str, str] | None = None) -> None:
        self.client = _FakeClient(peer_ip)
        self._headers = headers or {}

    @property
    def headers(self) -> dict[str, str]:
        return self._headers


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


def test_strip_port_ipv4() -> None:
    assert _strip_port("1.2.3.4:8080") == "1.2.3.4"


def test_strip_port_ipv4_no_port() -> None:
    assert _strip_port("1.2.3.4") == "1.2.3.4"


def test_strip_port_ipv6_bracketed_with_port() -> None:
    assert _strip_port("[::1]:8080") == "::1"


def test_strip_port_ipv6_bracketed_no_port() -> None:
    assert _strip_port("[::1]") == "::1"


def test_extract_forwarded_simple() -> None:
    assert _extract_from_forwarded("for=192.0.2.60") == "192.0.2.60"


def test_extract_forwarded_quoted_with_port() -> None:
    assert _extract_from_forwarded('for="192.0.2.60:8080"') == "192.0.2.60"


def test_extract_forwarded_ipv6() -> None:
    assert _extract_from_forwarded('for="[2001:db8::1]"') == "2001:db8::1"


def test_extract_forwarded_multiple_takes_first() -> None:
    assert _extract_from_forwarded("for=203.0.113.50, for=198.51.100.1") == "203.0.113.50"


def test_extract_forwarded_with_other_directives() -> None:
    assert _extract_from_forwarded("for=192.0.2.43;proto=https;by=203.0.113.60") == "192.0.2.43"


def test_extract_forwarded_empty() -> None:
    assert _extract_from_forwarded("proto=https") is None


def test_extract_xff_simple() -> None:
    assert _extract_from_x_forwarded_for("203.0.113.50") == "203.0.113.50"


def test_extract_xff_multiple_takes_first() -> None:
    assert _extract_from_x_forwarded_for("203.0.113.50, 198.51.100.1, 10.0.0.1") == "203.0.113.50"


def test_extract_xff_empty() -> None:
    assert _extract_from_x_forwarded_for("") is None


def test_parse_trusted_networks_valid() -> None:
    nets = _parse_trusted_networks("127.0.0.1, 10.0.0.0/8, ::1")
    assert len(nets) == 3


def test_parse_trusted_networks_empty() -> None:
    assert _parse_trusted_networks("") == []


def test_parse_trusted_networks_ignores_invalid() -> None:
    nets = _parse_trusted_networks("127.0.0.1, not-an-ip, 10.0.0.0/8")
    assert len(nets) == 2


# ---------------------------------------------------------------------------
# Integration tests for get_client_ip
# ---------------------------------------------------------------------------


def test_returns_peer_ip_when_no_trusted_proxies() -> None:
    req = _FakeRequest("10.0.0.1", {"x-forwarded-for": "203.0.113.50"})
    with patch("app.core.client_ip._trusted_networks", []):
        assert get_client_ip(req) == "10.0.0.1"  # type: ignore[arg-type]


def test_returns_peer_ip_when_peer_not_trusted() -> None:
    nets = _parse_trusted_networks("172.16.0.0/12")
    req = _FakeRequest("10.0.0.1", {"x-forwarded-for": "203.0.113.50"})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "10.0.0.1"  # type: ignore[arg-type]


def test_extracts_from_x_forwarded_for() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest("10.0.0.1", {"x-forwarded-for": "203.0.113.50, 10.0.0.1"})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "203.0.113.50"  # type: ignore[arg-type]


def test_extracts_from_forwarded_header() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest("10.0.0.1", {"forwarded": "for=203.0.113.50;proto=https"})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "203.0.113.50"  # type: ignore[arg-type]


def test_forwarded_takes_precedence_over_xff() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest(
        "10.0.0.1",
        {
            "forwarded": "for=198.51.100.1",
            "x-forwarded-for": "203.0.113.50",
        },
    )
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "198.51.100.1"  # type: ignore[arg-type]


def test_returns_peer_when_headers_empty() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest("10.0.0.1", {})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "10.0.0.1"  # type: ignore[arg-type]


def test_cidr_matching() -> None:
    nets = _parse_trusted_networks("10.0.0.0/8")
    req = _FakeRequest("10.255.0.1", {"x-forwarded-for": "203.0.113.50"})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "203.0.113.50"  # type: ignore[arg-type]


def test_strips_port_from_forwarded() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest("10.0.0.1", {"forwarded": 'for="192.0.2.60:8080"'})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "192.0.2.60"  # type: ignore[arg-type]


def test_strips_port_from_forwarded_ipv6() -> None:
    nets = _parse_trusted_networks("10.0.0.1")
    req = _FakeRequest("10.0.0.1", {"forwarded": 'for="[2001:db8::1]:9090"'})
    with patch("app.core.client_ip._trusted_networks", nets):
        assert get_client_ip(req) == "2001:db8::1"  # type: ignore[arg-type]
