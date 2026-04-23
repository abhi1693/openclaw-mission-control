"""OpenClaw gateway websocket RPC client and protocol constants.

This is the low-level, DB-free interface for talking to the OpenClaw gateway.
Keep gateway RPC protocol details and client helpers here so OpenClaw services
operate within a single scope (no `app.integrations.*` plumbing).
"""

from __future__ import annotations

import asyncio
import json
import platform as _platform
import re
import ssl
from dataclasses import dataclass
from time import perf_counter, time
from typing import Any, Literal
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4

import websockets
from websockets.exceptions import WebSocketException

from app.core.logging import TRACE_LEVEL, get_logger
from app.services.openclaw.device_identity import (
    build_device_auth_payload,
    load_or_create_device_identity,
    public_key_raw_base64url_from_pem,
    sign_device_payload,
)

PROTOCOL_VERSION = 3
# Resolved once at import time; matches the value written by the openclaw CLI
# during pairing ("linux", "darwin", or "windows").
_HOST_PLATFORM: str = _platform.system().lower()
logger = get_logger(__name__)
GATEWAY_OPERATOR_SCOPES = (
    "operator.read",
    "operator.admin",
    "operator.approvals",
    "operator.pairing",
)
DEFAULT_GATEWAY_CLIENT_ID = "gateway-client"
DEFAULT_GATEWAY_CLIENT_MODE = "backend"
CONTROL_UI_CLIENT_ID = "openclaw-control-ui"
CONTROL_UI_CLIENT_MODE = "ui"
GatewayConnectMode = Literal["device", "control_ui"]

# NOTE: These are the base gateway methods from the OpenClaw gateway repo.
# The gateway can expose additional methods at runtime via channel plugins.
# Updated for OpenClaw 2026.4.5 (3e72c03).
GATEWAY_METHODS = [
    "health",
    "logs.tail",
    "channels.status",
    "channels.logout",
    "status",
    "usage.status",
    "usage.cost",
    "tts.status",
    "tts.providers",
    "tts.enable",
    "tts.disable",
    "tts.convert",
    "tts.setProvider",
    "config.get",
    "config.set",
    "config.apply",
    "config.patch",
    "config.schema",
    "config.schema.lookup",
    "exec.approvals.get",
    "exec.approvals.set",
    "exec.approvals.node.get",
    "exec.approvals.node.set",
    "exec.approval.get",
    "exec.approval.request",
    "exec.approval.resolve",
    "exec.approval.waitDecision",
    "wizard.start",
    "wizard.next",
    "wizard.cancel",
    "wizard.status",
    "talk.mode",
    "talk.config",
    "talk.speak",
    "models.list",
    # Added 4.15 — Part E.1: strips credentials, caches 60s. Used by
    # the heartbeat watchdog to correlate repair events with provider
    # auth/rate-limit state.
    "models.authStatus",
    "agents.list",
    "agents.create",
    "agents.update",
    "agents.delete",
    "agents.files.list",
    "agents.files.get",
    "agents.files.set",
    "skills.status",
    "skills.bins",
    "skills.install",
    "skills.update",
    "skills.search",
    "skills.detail",
    "update.run",
    "voicewake.get",
    "voicewake.set",
    "sessions.list",
    "sessions.preview",
    "sessions.create",
    "sessions.patch",
    "sessions.reset",
    "sessions.delete",
    "sessions.compact",
    "sessions.send",
    "sessions.steer",
    "sessions.abort",
    "sessions.resolve",
    "sessions.subscribe",
    "sessions.unsubscribe",
    "sessions.messages.subscribe",
    "sessions.messages.unsubscribe",
    "last-heartbeat",
    "set-heartbeats",
    "wake",
    "secrets.reload",
    "secrets.resolve",
    "doctor.memory.status",
    "doctor.memory.dreamDiary",
    "tools.catalog",
    "tools.effective",
    "gateway.identity.get",
    "node.pair.request",
    "node.pair.list",
    "node.pair.approve",
    "node.pair.reject",
    "node.pair.verify",
    "node.pending.drain",
    "node.pending.enqueue",
    "node.pending.pull",
    "node.pending.ack",
    "node.canvas.capability.refresh",
    "device.pair.list",
    "device.pair.approve",
    "device.pair.reject",
    "device.pair.remove",
    "device.token.rotate",
    "device.token.revoke",
    "node.rename",
    "node.list",
    "node.describe",
    "node.invoke",
    "node.invoke.result",
    "node.event",
    "cron.list",
    "cron.status",
    "cron.add",
    "cron.update",
    "cron.remove",
    "cron.run",
    "cron.runs",
    "plugin.approval.request",
    "plugin.approval.resolve",
    "plugin.approval.waitDecision",
    "system-presence",
    "system-event",
    "send",
    "agent",
    "agent.identity.get",
    "agent.wait",
    "browser.request",
    "chat.history",
    "chat.abort",
    "chat.send",
]

# Updated for OpenClaw 2026.4.5 (3e72c03).
GATEWAY_EVENTS = [
    "connect.challenge",
    "agent",
    "chat",
    "presence",
    "tick",
    "talk.mode",
    "shutdown",
    "health",
    "heartbeat",
    "cron",
    "session.message",
    "session.tool",
    "sessions.changed",
    "node.pair.requested",
    "node.pair.resolved",
    "node.invoke.request",
    "device.pair.requested",
    "device.pair.resolved",
    "voicewake.changed",
    "exec.approval.requested",
    "exec.approval.resolved",
    "plugin.approval.requested",
    "plugin.approval.resolved",
    "update.available",
]

GATEWAY_METHODS_SET = frozenset(GATEWAY_METHODS)
GATEWAY_EVENTS_SET = frozenset(GATEWAY_EVENTS)


def is_known_gateway_method(method: str) -> bool:
    """Return whether a method name is part of the known base gateway methods."""
    return method in GATEWAY_METHODS_SET


class OpenClawGatewayError(RuntimeError):
    """Raised when OpenClaw gateway calls fail.

    Carries an optional ``details`` dict captured from the gateway's
    structured ``data["error"]`` frame. The protocol shape is defined
    at ``src/gateway/protocol/connect-error-details.ts`` upstream and
    typically includes ``code`` (e.g. ``PAIRING_REQUIRED``),
    ``requestId`` (correlation id operators use to cross-reference
    gateway logs), and reason-specific fields (``reason``,
    ``recommendedNextStep``, etc.). Consumers prefer structured
    fields — falling back to the human-readable message only when
    older gateways (pre-4.20) don't populate the structured path.

    ``str(exc)`` keeps returning the raw message for backward
    compatibility with existing log lines and the citation path.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details: dict[str, Any] | None = details

    @property
    def code(self) -> str | None:
        """Structured error code from ``data["error"]["code"]`` (e.g.
        ``PAIRING_REQUIRED``), or ``None`` when the gateway didn't
        populate it."""

        if not isinstance(self.details, dict):
            return None
        code = self.details.get("code")
        return code if isinstance(code, str) and code else None

    @property
    def request_id(self) -> str | None:
        """Structured correlation id from ``data["error"]["requestId"]``
        (or ``request_id`` in older gateway builds), or ``None``."""

        if not isinstance(self.details, dict):
            return None
        for key in ("requestId", "request_id"):
            value = self.details.get(key)
            if isinstance(value, str) and value:
                return value
        return None


@dataclass(frozen=True)
class GatewayConfig:
    """Connection configuration for the OpenClaw gateway."""

    url: str
    token: str | None = None
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False


def _is_expected_idempotent_gateway_error(method: str, exc: OpenClawGatewayError) -> bool:
    if method != "agents.create":
        return False
    message = str(exc).lower()
    return any(marker in message for marker in ("already", "exist", "duplicate", "conflict"))


def _build_gateway_url(config: GatewayConfig) -> str:
    base_url: str = (config.url or "").strip()
    if not base_url:
        message = "Gateway URL is not configured."
        raise OpenClawGatewayError(message)
    token = config.token
    if not token:
        return base_url
    parsed = urlparse(base_url)
    query = urlencode({"token": token})
    return str(urlunparse(parsed._replace(query=query)))


def _redacted_url_for_log(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    return str(urlunparse(parsed._replace(query="", fragment="")))


# Error messages flow from ``OpenClawGatewayError.__str__`` into
# operator-facing surfaces (Part D stale-agent Blocker citations). The
# gateway URL embeds ``?token=<shared-secret>`` via
# :func:`_build_gateway_url`, so any transport error that stringifies
# the URL (``ConnectionError``, ``OSError``, ``WebSocketException``)
# leaks the token into the Blocker row. Downstream callers must run
# this redactor before stamping the error message anywhere persisted
# or rendered to users.
#
# Patterns covered:
#   * ``?token=...`` / ``&token=...`` URL query params (any case)
#   * bare ``access_token=...`` / ``authorization: ...`` key=value
#   * JWT-shape tokens (``eyJ...`` three base64url segments)
#
# The redaction is intentionally conservative — leaves the rest of the
# message (URL host/path, errno, reason codes, request_id) intact so
# operators keep the signal they need.
_TOKEN_QUERY_RE = re.compile(
    r"([?&](?:token|access_token|apikey|auth|authorization)=)[^&\s]+",
    re.IGNORECASE,
)
_BARE_TOKEN_KV_RE = re.compile(
    r"\b((?:access_token|bearer|authorization)\s*[:=]\s*)[\w\-._+/]+",
    re.IGNORECASE,
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]+")


def redact_gateway_error_message(message: str) -> str:
    """Strip token-bearing substrings from a gateway error message so
    it's safe to persist in operator-facing surfaces."""

    redacted = _TOKEN_QUERY_RE.sub(r"\1<redacted>", message)
    redacted = _BARE_TOKEN_KV_RE.sub(r"\1<redacted>", redacted)
    redacted = _JWT_RE.sub("<redacted-jwt>", redacted)
    return redacted


def _create_ssl_context(config: GatewayConfig) -> ssl.SSLContext | None:
    """Create an insecure SSL context override for explicit opt-in TLS bypass.

    This behavior is intentionally host-agnostic: when ``allow_insecure_tls`` is
    enabled for a ``wss://`` gateway, certificate and hostname verification are
    disabled for that gateway connection.
    """
    parsed = urlparse(config.url)
    if parsed.scheme != "wss":
        return None
    if not config.allow_insecure_tls:
        return None
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


def _build_control_ui_origin(gateway_url: str) -> str | None:
    parsed = urlparse(gateway_url)
    if not parsed.hostname:
        return None
    if parsed.scheme in {"ws", "http"}:
        origin_scheme = "http"
    elif parsed.scheme in {"wss", "https"}:
        origin_scheme = "https"
    else:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{origin_scheme}://{host}"


def _resolve_connect_mode(config: GatewayConfig) -> GatewayConnectMode:
    return "control_ui" if config.disable_device_pairing else "device"


def _build_device_connect_payload(
    *,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    auth_token: str | None,
    connect_nonce: str | None,
) -> dict[str, Any]:
    identity = load_or_create_device_identity()
    signed_at_ms = int(time() * 1000)
    payload = build_device_auth_payload(
        device_id=identity.device_id,
        client_id=client_id,
        client_mode=client_mode,
        role=role,
        scopes=scopes,
        signed_at_ms=signed_at_ms,
        token=auth_token,
        nonce=connect_nonce,
    )
    device_payload: dict[str, Any] = {
        "id": identity.device_id,
        "publicKey": public_key_raw_base64url_from_pem(identity.public_key_pem),
        "signature": sign_device_payload(identity.private_key_pem, payload),
        "signedAt": signed_at_ms,
    }
    if connect_nonce:
        device_payload["nonce"] = connect_nonce
    return device_payload


async def _await_response(
    ws: websockets.ClientConnection,
    request_id: str,
) -> object:
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        logger.log(
            TRACE_LEVEL,
            "gateway.rpc.recv request_id=%s type=%s",
            request_id,
            data.get("type"),
        )

        if data.get("type") == "res" and data.get("id") == request_id:
            ok = data.get("ok")
            if ok is not None and not ok:
                error_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
                message = error_obj.get("message", "Gateway error")
                raise OpenClawGatewayError(message, details=error_obj or None)
            return data.get("payload")

        if data.get("id") == request_id:
            error_obj = data.get("error")
            if error_obj:
                error_dict = error_obj if isinstance(error_obj, dict) else {}
                message = error_dict.get("message", "Gateway error")
                raise OpenClawGatewayError(message, details=error_dict or None)
            return data.get("result")


async def _send_request(
    ws: websockets.ClientConnection,
    method: str,
    params: dict[str, Any] | None,
) -> object:
    request_id = str(uuid4())
    message = {
        "type": "req",
        "id": request_id,
        "method": method,
        "params": params or {},
    }
    logger.log(
        TRACE_LEVEL,
        "gateway.rpc.send method=%s request_id=%s params_keys=%s",
        method,
        request_id,
        sorted((params or {}).keys()),
    )
    await ws.send(json.dumps(message))
    return await _await_response(ws, request_id)


def _build_connect_params(
    config: GatewayConfig,
    *,
    connect_nonce: str | None = None,
) -> dict[str, Any]:
    role = "operator"
    scopes = list(GATEWAY_OPERATOR_SCOPES)
    connect_mode = _resolve_connect_mode(config)
    use_control_ui = connect_mode == "control_ui"
    params: dict[str, Any] = {
        "minProtocol": PROTOCOL_VERSION,
        "maxProtocol": PROTOCOL_VERSION,
        "role": role,
        "scopes": scopes,
        "client": {
            "id": CONTROL_UI_CLIENT_ID if use_control_ui else DEFAULT_GATEWAY_CLIENT_ID,
            "version": "1.0.0",
            "platform": _HOST_PLATFORM,
            "mode": CONTROL_UI_CLIENT_MODE if use_control_ui else DEFAULT_GATEWAY_CLIENT_MODE,
        },
    }
    if not use_control_ui:
        params["device"] = _build_device_connect_payload(
            client_id=DEFAULT_GATEWAY_CLIENT_ID,
            client_mode=DEFAULT_GATEWAY_CLIENT_MODE,
            role=role,
            scopes=scopes,
            auth_token=config.token,
            connect_nonce=connect_nonce,
        )
    if config.token:
        params["auth"] = {"token": config.token}
    return params


async def _ensure_connected(
    ws: websockets.ClientConnection,
    first_message: str | bytes | None,
    config: GatewayConfig,
) -> object:
    connect_nonce: str | None = None
    if first_message:
        if isinstance(first_message, bytes):
            first_message = first_message.decode("utf-8")
        data = json.loads(first_message)
        if data.get("type") == "event" and data.get("event") == "connect.challenge":
            payload = data.get("payload")
            if isinstance(payload, dict):
                nonce = payload.get("nonce")
                if isinstance(nonce, str) and nonce.strip():
                    connect_nonce = nonce.strip()
        else:
            logger.warning(
                "gateway.rpc.connect.unexpected_first_message type=%s event=%s",
                data.get("type"),
                data.get("event"),
            )
    connect_id = str(uuid4())
    response = {
        "type": "req",
        "id": connect_id,
        "method": "connect",
        "params": _build_connect_params(config, connect_nonce=connect_nonce),
    }
    await ws.send(json.dumps(response))
    return await _await_response(ws, connect_id)


async def _recv_first_message_or_none(
    ws: websockets.ClientConnection,
) -> str | bytes | None:
    try:
        return await asyncio.wait_for(ws.recv(), timeout=2)
    except TimeoutError:
        return None


async def _openclaw_call_once(
    method: str,
    params: dict[str, Any] | None,
    *,
    config: GatewayConfig,
    gateway_url: str,
) -> object:
    origin = _build_control_ui_origin(gateway_url) if config.disable_device_pairing else None
    ssl_context = _create_ssl_context(config)
    connect_kwargs: dict[str, Any] = {"ping_interval": None}
    if origin is not None:
        connect_kwargs["origin"] = origin
    if ssl_context is not None:
        connect_kwargs["ssl"] = ssl_context
    async with websockets.connect(gateway_url, **connect_kwargs) as ws:
        first_message = await _recv_first_message_or_none(ws)
        await _ensure_connected(ws, first_message, config)
        return await _send_request(ws, method, params)


async def _openclaw_connect_metadata_once(
    *,
    config: GatewayConfig,
    gateway_url: str,
) -> object:
    origin = _build_control_ui_origin(gateway_url) if config.disable_device_pairing else None
    ssl_context = _create_ssl_context(config)
    connect_kwargs: dict[str, Any] = {"ping_interval": None}
    if origin is not None:
        connect_kwargs["origin"] = origin
    if ssl_context is not None:
        connect_kwargs["ssl"] = ssl_context
    async with websockets.connect(gateway_url, **connect_kwargs) as ws:
        first_message = await _recv_first_message_or_none(ws)
        return await _ensure_connected(ws, first_message, config)


async def openclaw_call(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    config: GatewayConfig,
) -> object:
    """Call a gateway RPC method and return the result payload."""
    gateway_url = _build_gateway_url(config)
    started_at = perf_counter()
    logger.debug(
        (
            "gateway.rpc.call.start method=%s gateway_url=%s allow_insecure_tls=%s "
            "disable_device_pairing=%s"
        ),
        method,
        _redacted_url_for_log(gateway_url),
        config.allow_insecure_tls,
        config.disable_device_pairing,
    )
    try:
        payload = await _openclaw_call_once(
            method,
            params,
            config=config,
            gateway_url=gateway_url,
        )
        logger.debug(
            "gateway.rpc.call.success method=%s duration_ms=%s",
            method,
            int((perf_counter() - started_at) * 1000),
        )
        return payload
    except OpenClawGatewayError as exc:
        if _is_expected_idempotent_gateway_error(method, exc):
            logger.info(
                "gateway.rpc.call.gateway_expected_error method=%s duration_ms=%s",
                method,
                int((perf_counter() - started_at) * 1000),
            )
        else:
            logger.warning(
                "gateway.rpc.call.gateway_error method=%s duration_ms=%s",
                method,
                int((perf_counter() - started_at) * 1000),
            )
        raise
    except (
        TimeoutError,
        ConnectionError,
        OSError,
        ValueError,
        WebSocketException,
    ) as exc:  # pragma: no cover - network/protocol errors
        logger.error(
            "gateway.rpc.call.transport_error method=%s duration_ms=%s error_type=%s",
            method,
            int((perf_counter() - started_at) * 1000),
            exc.__class__.__name__,
        )
        raise OpenClawGatewayError(str(exc)) from exc


async def openclaw_connect_metadata(*, config: GatewayConfig) -> object:
    """Open a gateway connection and return the connect/hello payload."""
    gateway_url = _build_gateway_url(config)
    started_at = perf_counter()
    logger.debug(
        "gateway.rpc.connect_metadata.start gateway_url=%s",
        _redacted_url_for_log(gateway_url),
    )
    try:
        metadata = await _openclaw_connect_metadata_once(
            config=config,
            gateway_url=gateway_url,
        )
        logger.debug(
            "gateway.rpc.connect_metadata.success duration_ms=%s",
            int((perf_counter() - started_at) * 1000),
        )
        return metadata
    except OpenClawGatewayError:
        logger.warning(
            "gateway.rpc.connect_metadata.gateway_error duration_ms=%s",
            int((perf_counter() - started_at) * 1000),
        )
        raise
    except (
        TimeoutError,
        ConnectionError,
        OSError,
        ValueError,
        WebSocketException,
    ) as exc:  # pragma: no cover - network/protocol errors
        logger.error(
            "gateway.rpc.connect_metadata.transport_error duration_ms=%s error_type=%s",
            int((perf_counter() - started_at) * 1000),
            exc.__class__.__name__,
        )
        raise OpenClawGatewayError(str(exc)) from exc


async def models_auth_status(
    *, config: GatewayConfig
) -> dict[str, Any] | None:
    """Call ``models.authStatus`` on the gateway (4.15+).

    Returns the raw snapshot dict on success, ``None`` on any failure
    — unknown-method, transport error, unexpected payload shape. The
    watchdog's repair-event forensics path is the main consumer; a
    missing snapshot is acceptable (older gateway / degraded transport)
    and must not block repair itself.
    """

    try:
        result = await openclaw_call(
            "models.authStatus",
            None,
            config=config,
        )
    except OpenClawGatewayError:
        logger.debug(
            "gateway.rpc.models_auth_status.gateway_error",
            exc_info=False,
        )
        return None
    except Exception:  # pragma: no cover - defensive catch-all
        logger.exception("gateway.rpc.models_auth_status.unexpected_error")
        return None
    if not isinstance(result, dict):
        return None
    return result


async def send_message(
    message: str,
    *,
    session_key: str,
    config: GatewayConfig,
    deliver: bool = False,
) -> object:
    """Send a chat message to a session."""
    params: dict[str, Any] = {
        "sessionKey": session_key,
        "message": message,
        "deliver": deliver,
        "idempotencyKey": str(uuid4()),
    }
    return await openclaw_call("chat.send", params, config=config)


async def abort_session(session_key: str, *, config: GatewayConfig) -> object:
    """Abort the current run in a session."""
    return await openclaw_call("chat.abort", {"sessionKey": session_key}, config=config)


async def get_chat_history(
    session_key: str,
    config: GatewayConfig,
    limit: int | None = None,
) -> object:
    """Fetch chat history for a session."""
    params: dict[str, Any] = {"sessionKey": session_key}
    if limit is not None:
        params["limit"] = limit
    return await openclaw_call("chat.history", params, config=config)


async def delete_session(session_key: str, *, config: GatewayConfig) -> object:
    """Delete a session by key."""
    return await openclaw_call("sessions.delete", {"key": session_key}, config=config)


async def ensure_session(
    session_key: str,
    *,
    config: GatewayConfig,
    label: str | None = None,
) -> object:
    """Ensure a session exists and optionally update its label."""
    params: dict[str, Any] = {"key": session_key}
    if label:
        params["label"] = label
    return await openclaw_call("sessions.patch", params, config=config)


# ---------------------------------------------------------------------------
# 2026.4.5 helpers
# ---------------------------------------------------------------------------


async def steer_session(
    message: str,
    *,
    session_key: str,
    config: GatewayConfig,
    deliver: bool = False,
) -> object:
    """Send a message with interruptIfActive — interrupts a stuck agent run."""
    params: dict[str, Any] = {
        "sessionKey": session_key,
        "message": message,
        "deliver": deliver,
        "interruptIfActive": True,
        "idempotencyKey": str(uuid4()),
    }
    return await openclaw_call("sessions.steer", params, config=config)


async def reload_secrets(*, config: GatewayConfig) -> object:
    """Re-resolve secret references and swap the runtime snapshot."""
    return await openclaw_call("secrets.reload", config=config)


async def create_session(
    *,
    config: GatewayConfig,
    agent_id: str | None = None,
    label: str | None = None,
    model: str | None = None,
    parent_session_key: str | None = None,
    message: str | None = None,
) -> object:
    """Create a new session, optionally triggering a run with an initial message."""
    params: dict[str, Any] = {}
    if agent_id:
        params["agentId"] = agent_id
    if label:
        params["label"] = label
    if model:
        params["model"] = model
    if parent_session_key:
        params["parentSessionKey"] = parent_session_key
    if message:
        params["message"] = message
    return await openclaw_call("sessions.create", params, config=config)


async def get_tools_effective(
    session_key: str,
    *,
    config: GatewayConfig,
) -> object:
    """Get the effective tool inventory for a session."""
    return await openclaw_call(
        "tools.effective", {"sessionKey": session_key}, config=config
    )


async def get_memory_status(
    agent_id: str,
    *,
    config: GatewayConfig,
) -> object:
    """Get memory/embedding/dreaming status for an agent."""
    return await openclaw_call(
        "doctor.memory.status", {"agentId": agent_id}, config=config
    )
