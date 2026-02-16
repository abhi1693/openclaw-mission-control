"""OpenClaw gateway websocket RPC client and protocol constants.

This is the low-level, DB-free interface for talking to the OpenClaw gateway.
Keep gateway RPC protocol details and client helpers here so OpenClaw services
operate within a single scope (no `app.integrations.*` plumbing).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from websockets.exceptions import WebSocketException

from app.core.logging import TRACE_LEVEL, get_logger

PROTOCOL_VERSION = 3
logger = get_logger(__name__)
GATEWAY_OPERATOR_SCOPES = (
    "operator.admin",
    "operator.approvals",
    "operator.pairing",
    "operator.read",
)

# ---------------------------------------------------------------------------
# Device-key authentication helpers
# ---------------------------------------------------------------------------
_DEVICE_KEY_DIR = Path(__file__).resolve().parent / ".device-keys"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _get_or_create_device_keypair() -> tuple[Ed25519PrivateKey, bytes, str]:
    """Return (private_key, raw_public_bytes, device_id).

    Keys are persisted to ``_DEVICE_KEY_DIR`` so the device identity remains
    stable across restarts (avoiding repeated pairing prompts).
    """
    _DEVICE_KEY_DIR.mkdir(parents=True, exist_ok=True)
    key_path = _DEVICE_KEY_DIR / "device.key"
    if key_path.exists():
        raw = key_path.read_bytes()
        private_key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    else:
        private_key = Ed25519PrivateKey.generate()
        raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        key_path.write_bytes(raw)
        key_path.chmod(0o600)
    pub_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    device_id = hashlib.sha256(pub_bytes).hexdigest()
    return private_key, pub_bytes, device_id


def _build_device_auth(
    *,
    token: str,
    nonce: str,
    scopes: list[str],
    device_id: str,
    private_key: Ed25519PrivateKey,
    pub_bytes: bytes,
) -> dict[str, Any]:
    """Build the ``device`` block for the connect handshake."""
    signed_at = int(time.time() * 1000)
    scopes_str = ",".join(scopes)
    payload = (
        f"v2|{device_id}|gateway-client|ui|operator|"
        f"{scopes_str}|{signed_at}|{token}|{nonce}"
    )
    signature = private_key.sign(payload.encode())
    return {
        "id": device_id,
        "publicKey": _b64url(pub_bytes),
        "signature": _b64url(signature),
        "signedAt": signed_at,
        "nonce": nonce,
    }


# NOTE: These are the base gateway methods from the OpenClaw gateway repo.
# The gateway can expose additional methods at runtime via channel plugins.
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
    "exec.approvals.get",
    "exec.approvals.set",
    "exec.approvals.node.get",
    "exec.approvals.node.set",
    "exec.approval.request",
    "exec.approval.resolve",
    "wizard.start",
    "wizard.next",
    "wizard.cancel",
    "wizard.status",
    "talk.mode",
    "models.list",
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
    "update.run",
    "voicewake.get",
    "voicewake.set",
    "sessions.list",
    "sessions.preview",
    "sessions.patch",
    "sessions.reset",
    "sessions.delete",
    "sessions.compact",
    "last-heartbeat",
    "set-heartbeats",
    "wake",
    "node.pair.request",
    "node.pair.list",
    "node.pair.approve",
    "node.pair.reject",
    "node.pair.verify",
    "device.pair.list",
    "device.pair.approve",
    "device.pair.reject",
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
    "node.pair.requested",
    "node.pair.resolved",
    "node.invoke.request",
    "device.pair.requested",
    "device.pair.resolved",
    "voicewake.changed",
    "exec.approval.requested",
    "exec.approval.resolved",
]

GATEWAY_METHODS_SET = frozenset(GATEWAY_METHODS)
GATEWAY_EVENTS_SET = frozenset(GATEWAY_EVENTS)


def is_known_gateway_method(method: str) -> bool:
    """Return whether a method name is part of the known base gateway methods."""
    return method in GATEWAY_METHODS_SET


class OpenClawGatewayError(RuntimeError):
    """Raised when OpenClaw gateway calls fail."""


@dataclass(frozen=True)
class GatewayConfig:
    """Connection configuration for the OpenClaw gateway."""

    url: str
    token: str | None = None


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
                error = data.get("error", {}).get("message", "Gateway error")
                raise OpenClawGatewayError(error)
            return data.get("payload")

        if data.get("id") == request_id:
            if data.get("error"):
                message = data["error"].get("message", "Gateway error")
                raise OpenClawGatewayError(message)
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
    nonce: str = "",
) -> dict[str, Any]:
    scopes = list(GATEWAY_OPERATOR_SCOPES)
    params: dict[str, Any] = {
        "minProtocol": PROTOCOL_VERSION,
        "maxProtocol": PROTOCOL_VERSION,
        "role": "operator",
        "scopes": scopes,
        "client": {
            "id": "gateway-client",
            "version": "1.0.0",
            "platform": "web",
            "mode": "ui",
        },
    }
    if config.token:
        params["auth"] = {"token": config.token}
        # Device-key auth: sign the challenge nonce so the gateway preserves
        # the requested scopes (without this, scopes are stripped).
        try:
            private_key, pub_bytes, device_id = _get_or_create_device_keypair()
            params["device"] = _build_device_auth(
                token=config.token,
                nonce=nonce,
                scopes=scopes,
                device_id=device_id,
                private_key=private_key,
                pub_bytes=pub_bytes,
            )
        except Exception:
            logger.warning("gateway.rpc.device_auth_failed", exc_info=True)
    return params


async def _ensure_connected(
    ws: websockets.ClientConnection,
    first_message: str | bytes | None,
    config: GatewayConfig,
) -> None:
    nonce = ""
    if first_message:
        if isinstance(first_message, bytes):
            first_message = first_message.decode("utf-8")
        data = json.loads(first_message)
        if data.get("type") == "event" and data.get("event") == "connect.challenge":
            nonce = data.get("payload", {}).get("nonce", "")
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
        "params": _build_connect_params(config, nonce=nonce),
    }
    await ws.send(json.dumps(response))
    await _await_response(ws, connect_id)


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
        "gateway.rpc.call.start method=%s gateway_url=%s",
        method,
        _redacted_url_for_log(gateway_url),
    )
    try:
        async with websockets.connect(gateway_url, ping_interval=None) as ws:
            first_message = None
            try:
                first_message = await asyncio.wait_for(ws.recv(), timeout=2)
            except TimeoutError:
                first_message = None
            await _ensure_connected(ws, first_message, config)
            payload = await _send_request(ws, method, params)
            logger.debug(
                "gateway.rpc.call.success method=%s duration_ms=%s",
                method,
                int((perf_counter() - started_at) * 1000),
            )
            return payload
    except OpenClawGatewayError:
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
