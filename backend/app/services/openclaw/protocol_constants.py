"""Lightweight protocol constants shared by the OpenClaw gateway RPC
client and the long-lived event subscriber.

Intentionally has NO dependencies on ``app.core.*`` (config, logging,
settings) so worker processes that consume only protocol constants —
e.g. ``mc_gateway_subscriber`` running under systemd with a minimal
env — can import them without instantiating the full FastAPI
``Settings`` object.

Keep this module dependency-free. If a constant needs computed
state, derive it lazily in the call site, not here.
"""

from __future__ import annotations

import platform as _platform
from urllib.parse import urlparse

# Bumped historically; matches the gateway repo. Both
# ``gateway_rpc.py`` (one-shot RPC) and ``mc_gateway_subscriber``
# (long-lived) import from here so they cannot drift.
PROTOCOL_VERSION = 3

# Operator role + scopes for backend-style clients (MC backend, the
# gateway-event subscriber). Distinct from per-agent X-Agent-Token
# auth used by the agent-namespace HTTP routes.
OPERATOR_ROLE = "operator"
GATEWAY_OPERATOR_SCOPES: tuple[str, ...] = (
    "operator.read",
    "operator.admin",
    "operator.approvals",
    "operator.pairing",
)

# Control-UI client identity. The gateway validates ``client.id`` and
# ``client.mode`` against allowed values; arbitrary strings are
# rejected at connect-time. These two are the canonical control-UI
# identifiers from the upstream gateway repo.
CONTROL_UI_CLIENT_ID = "openclaw-control-ui"
CONTROL_UI_CLIENT_MODE = "ui"

# Event names emitted by the gateway in ``type=event`` frames. Add
# entries here as projectors start consuming new variants — keeps the
# string out of handler-registration sites and makes refactors greppable.
EVENT_SESSIONS_CHANGED = "sessions.changed"

# Resolved once at import time; matches the value the openclaw CLI
# writes during pairing ("linux", "darwin", or "windows").
HOST_PLATFORM: str = _platform.system().lower()


def build_control_ui_connect_params(
    *,
    token: str,
    protocol_version: int = PROTOCOL_VERSION,
) -> dict[str, object]:
    """Build the ``params`` dict for a ``connect`` req in control-UI
    mode (i.e. no device-pairing crypto). Symmetric with
    ``gateway_rpc._build_connect_params`` when
    ``disable_device_pairing=True``.

    Note: ``connectNonce`` is intentionally NOT placed at the root —
    the gateway only accepts it inside the ``device`` payload, which
    control-UI mode doesn't send. The subscriber drops the nonce on
    the floor in control-UI mode.
    """
    return {
        "minProtocol": protocol_version,
        "maxProtocol": protocol_version,
        "role": OPERATOR_ROLE,
        "scopes": list(GATEWAY_OPERATOR_SCOPES),
        "client": {
            "id": CONTROL_UI_CLIENT_ID,
            "version": "1.0.0",
            "platform": HOST_PLATFORM,
            "mode": CONTROL_UI_CLIENT_MODE,
        },
        "auth": {"token": token},
    }


def build_control_ui_origin(gateway_url: str) -> str | None:
    """Construct the ``Origin`` header the gateway expects for
    control-UI WS connections. Single source of truth shared by the
    gateway RPC client and the long-lived event subscriber.
    """
    parsed = urlparse(gateway_url)
    if not parsed.hostname:
        return None
    if parsed.scheme in {"ws", "http"}:
        scheme = "http"
    elif parsed.scheme in {"wss", "https"}:
        scheme = "https"
    else:
        return None
    host = parsed.hostname
    # Bracket bare IPv6 hostnames; urlparse strips brackets on parse,
    # but the Origin header re-introduces them or the gateway rejects
    # the colons as a malformed port.
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{scheme}://{host}"
