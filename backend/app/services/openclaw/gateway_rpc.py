"""OpenClaw gateway websocket RPC client and protocol constants.

This is the low-level, DB-free interface for talking to the OpenClaw gateway.
Keep gateway RPC protocol details and client helpers here so OpenClaw services
operate within a single scope (no `app.integrations.*` plumbing).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4

import websockets
from websockets.exceptions import WebSocketException

from app.core.logging import TRACE_LEVEL, get_logger

PROTOCOL_VERSION = 3
logger = get_logger(__name__)
GATEWAY_OPERATOR_SCOPES = (
    "operator.admin",
    "operator.approvals",
    "operator.pairing",
)

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


def _build_connect_params(config: GatewayConfig) -> dict[str, Any]:
    params: dict[str, Any] = {
        "minProtocol": PROTOCOL_VERSION,
        "maxProtocol": PROTOCOL_VERSION,
        "role": "operator",
        "scopes": list(GATEWAY_OPERATOR_SCOPES),
        "client": {
            "id": "gateway-client",
            "version": "1.0.0",
            "platform": "web",
            "mode": "ui",
        },
    }
    if config.token:
        params["auth"] = {"token": config.token}
    return params


async def _ensure_connected(
    ws: websockets.ClientConnection,
    first_message: str | bytes | None,
    config: GatewayConfig,
) -> None:
    if first_message:
        if isinstance(first_message, bytes):
            first_message = first_message.decode("utf-8")
        data = json.loads(first_message)
        if data.get("type") != "event" or data.get("event") != "connect.challenge":
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
        "params": _build_connect_params(config),
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
