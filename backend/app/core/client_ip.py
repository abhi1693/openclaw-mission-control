"""Trusted client-IP extraction from proxy headers.

In proxied deployments ``request.client.host`` returns the reverse-proxy
IP.  This module provides :func:`get_client_ip` which inspects the
``Forwarded`` and ``X-Forwarded-For`` headers **only** when the direct
peer is in the configured ``TRUSTED_PROXIES`` list.
"""

from __future__ import annotations

import ipaddress
import re
from ipaddress import IPv4Network, IPv6Network
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import Request

logger = get_logger(__name__)

# RFC 7239 ``for=`` directive value.  Handles quoted/unquoted, optional
# port, and IPv6 bracket notation.
_FORWARDED_FOR_RE = re.compile(r'for="?(\[[^\]]+\]|[^";,\s]+)', re.IGNORECASE)


def _parse_trusted_networks(raw: str) -> list[IPv4Network | IPv6Network]:
    """Parse a comma-separated list of IPs/CIDRs into network objects."""
    networks: list[IPv4Network | IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("trusted_proxies: ignoring invalid entry %r", entry)
    return networks


def _is_trusted(peer_ip: str, networks: list[IPv4Network | IPv6Network]) -> bool:
    """Check whether *peer_ip* falls within any trusted network."""
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def _strip_port(raw: str) -> str:
    """Strip port suffix from a ``Forwarded: for=`` value.

    Handles ``1.2.3.4:8080``, ``[::1]:8080``, and bare addresses.
    """
    # Bracketed IPv6: ``[::1]:port`` or ``[::1]``
    if raw.startswith("["):
        bracket_end = raw.find("]")
        if bracket_end != -1:
            return raw[1:bracket_end]
        return raw.strip("[]")
    # IPv4 with port: ``1.2.3.4:8080``
    if "." in raw and ":" in raw:
        return raw.rsplit(":", 1)[0]
    return raw


def _extract_from_forwarded(header: str) -> str | None:
    """Return the leftmost ``for=`` client IP from an RFC 7239 Forwarded header."""
    match = _FORWARDED_FOR_RE.search(header)
    if not match:
        return None
    value = _strip_port(match.group(1))
    return value or None


def _extract_from_x_forwarded_for(header: str) -> str | None:
    """Return the leftmost entry from an X-Forwarded-For header."""
    first = header.split(",", 1)[0].strip()
    return first or None


def get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting proxy headers when trusted.

    Falls back to ``request.client.host`` when no trusted proxies are
    configured or the direct peer is not trusted.
    """
    peer_ip = request.client.host if request.client else "unknown"

    if not _trusted_networks:
        return peer_ip

    if not _is_trusted(peer_ip, _trusted_networks):
        return peer_ip

    # Prefer standardized Forwarded header (RFC 7239).
    forwarded = request.headers.get("forwarded")
    if forwarded:
        client_ip = _extract_from_forwarded(forwarded)
        if client_ip:
            return client_ip

    # Fall back to de-facto X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        client_ip = _extract_from_x_forwarded_for(xff)
        if client_ip:
            return client_ip

    return peer_ip


def _load_trusted_networks() -> list[IPv4Network | IPv6Network]:
    """Load trusted proxy networks from settings (called once at import)."""
    from app.core.config import settings

    return _parse_trusted_networks(settings.trusted_proxies)


_trusted_networks: list[IPv4Network | IPv6Network] = _load_trusted_networks()
