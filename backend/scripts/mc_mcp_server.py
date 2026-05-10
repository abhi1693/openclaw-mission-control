#!/usr/bin/env python3
"""Mission Control MCP server — exposes MC board API endpoints as typed
MCP tools for ACP children (Claude / Codex / OpenCode) and any other MCP
client.

Replaces the curl-with-auth-token construction pattern in agent skills
with typed tool calls via the standard Model Context Protocol stdio
transport. Runs as a separate process spawned by ACPX (or any other
MCP host). Auth and board id come from environment variables provided
by the spawn parent.

Wire-up in ``openclaw.json`` for ACPX::

    plugins.entries.acpx.config.mcpServers.mc-board-api = {
      "command": "python3",
      "args": ["/usr/local/bin/mc_mcp_server.py"],
      "env": {
        "LOCAL_AUTH_TOKEN": "<token>",
        "BOARD_ID": "<board-uuid>",
        "MC_BASE_URL": "http://192.168.2.64:8000"
      }
    }

After restart, ACP children automatically see ``mc_task_read``,
``mc_comment_create``, ``mc_pipeline_event_create``, and
``mc_review_event_create`` as available MCP tools.

Implements MCP 2024-11-05 protocol (JSON-RPC 2.0 over stdio):
  initialize, notifications/initialized, tools/list, tools/call.

No external SDK dependency — the protocol surface we need is small and
stdlib-only is more portable across deployments. If the gateway needs
richer MCP features later (resources, prompts, completions), swap in
the official ``mcp`` Python SDK; for now the surface this server
implements is the minimum that ACPX clients consume.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from typing import Any

LOG = logging.getLogger("mc_mcp_server")
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "mc-board-api"
SERVER_VERSION = "0.1.0"

DEFAULT_BASE_URL = "http://192.168.2.64:8000"


# --- HTTP plumbing (mirrors mc_client.py for consistency; intentionally
# duplicated rather than imported so this script has no PYTHONPATH dep
# beyond stdlib — both this server and the CLI deploy to /usr/local/bin
# as standalone scripts) ---


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def _request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, body) from exc
    if not raw:
        return {}
    return json.loads(raw)


def _resolve_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if not value:
        raise RuntimeError(
            f"required environment variable {name!r} not set; ACPX spawn "
            "parent should provide it"
        )
    return value


def _base_url() -> str:
    return os.environ.get("MC_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


# --- MC API operations (each MCP tool maps to one of these) ---


def op_task_read(task_id: str) -> dict[str, Any]:
    token = _resolve_env("LOCAL_AUTH_TOKEN")
    board = _resolve_env("BOARD_ID")
    base = _base_url()
    return _request(
        method="GET",
        url=f"{base}/api/v1/boards/{board}/tasks/{task_id}",
        token=token,
    )


def op_comment_create(task_id: str, message: str) -> dict[str, Any]:
    token = _resolve_env("LOCAL_AUTH_TOKEN")
    board = _resolve_env("BOARD_ID")
    base = _base_url()
    if not message or not message.strip():
        raise ValueError("message must be non-empty")
    return _request(
        method="POST",
        url=f"{base}/api/v1/boards/{board}/tasks/{task_id}/comments",
        token=token,
        payload={"message": message},
    )


def op_pipeline_event_create(
    task_id: str,
    state: str,
    *,
    source: str = "mc_mcp_server.py",
    commit_sha: str | None = None,
    artifact_hash: str | None = None,
    deploy_target: str | None = None,
    live_sha: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = _resolve_env("LOCAL_AUTH_TOKEN")
    board = _resolve_env("BOARD_ID")
    base = _base_url()
    payload: dict[str, Any] = {"state": state, "source": source}
    if commit_sha:
        payload["commit_sha"] = commit_sha
    if artifact_hash:
        payload["artifact_hash"] = artifact_hash
    if deploy_target:
        payload["deploy_target"] = deploy_target
    if live_sha:
        payload["live_sha"] = live_sha
    if evidence is not None:
        payload["evidence"] = evidence
    return _request(
        method="POST",
        url=f"{base}/api/v1/boards/{board}/tasks/{task_id}/pipeline/events",
        token=token,
        payload=payload,
    )


def op_review_event_create(
    task_id: str,
    reviewer_role: str,
    verdict: str,
    *,
    evidence_type: str | None = None,
    target: str | None = None,
    build_hash: str | None = None,
    source_commit: str | None = None,
    blocking_owner: str | None = None,
    suggested_routing: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = _resolve_env("LOCAL_AUTH_TOKEN")
    board = _resolve_env("BOARD_ID")
    base = _base_url()
    payload: dict[str, Any] = {"reviewer_role": reviewer_role, "verdict": verdict}
    if evidence_type:
        payload["evidence_type"] = evidence_type
    if target:
        payload["target"] = target
    if build_hash:
        payload["build_hash"] = build_hash
    if source_commit:
        payload["source_commit"] = source_commit
    if blocking_owner:
        payload["blocking_owner"] = blocking_owner
    if suggested_routing:
        payload["suggested_routing"] = suggested_routing
    if evidence is not None:
        payload["evidence"] = evidence
    return _request(
        method="POST",
        url=f"{base}/api/v1/boards/{board}/tasks/{task_id}/review-events",
        token=token,
        payload=payload,
    )


# --- MCP tool definitions ---


TOOLS: list[dict[str, Any]] = [
    {
        "name": "mc_task_read",
        "description": (
            "Read a Mission Control task by id from the configured board. "
            "Returns the full task envelope (id, title, description, "
            "status, priority, packet metadata)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task UUID. Required.",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "mc_comment_create",
        "description": (
            "Post a comment on an MC task. Use Markdown for the body. "
            "For multi-paragraph or generated content, build the string "
            "in your tool call rather than escaping nested quotes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task UUID."},
                "message": {
                    "type": "string",
                    "description": "Comment body (Markdown). Required, non-empty.",
                },
            },
            "required": ["task_id", "message"],
        },
    },
    {
        "name": "mc_pipeline_event_create",
        "description": (
            "Append a structured pipeline event to a task cycle. The "
            "state must be one of: code_changed, committed, built, "
            "deployed, live_build_verified, runtime_verified, qa_ready, "
            "model_fallback. For state=model_fallback, evidence MUST "
            "include from_model, to_model, and reason."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "state": {
                    "type": "string",
                    "enum": [
                        "code_changed",
                        "committed",
                        "built",
                        "deployed",
                        "live_build_verified",
                        "runtime_verified",
                        "qa_ready",
                        "model_fallback",
                    ],
                },
                "source": {"type": "string", "default": "mc_mcp_server.py"},
                "commit_sha": {"type": "string"},
                "artifact_hash": {"type": "string"},
                "deploy_target": {"type": "string"},
                "live_sha": {"type": "string"},
                "evidence": {
                    "type": "object",
                    "description": (
                        "Optional evidence dict. Required for "
                        "state=model_fallback with from_model, to_model, "
                        "reason."
                    ),
                },
            },
            "required": ["task_id", "state"],
        },
    },
    {
        "name": "mc_review_event_create",
        "description": (
            "Post a structured review verdict (Architect, QA-Unit, "
            "QA-E2E, DevOps, or Lead). Verdict choices: pass, fail, "
            "inconclusive, infra_blocked. ``partial`` is NOT valid."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "reviewer_role": {
                    "type": "string",
                    "enum": ["architect", "qa_unit", "qa_e2e", "devops", "lead"],
                },
                "verdict": {
                    "type": "string",
                    "enum": ["pass", "fail", "inconclusive", "infra_blocked"],
                },
                "evidence_type": {"type": "string"},
                "target": {"type": "string"},
                "build_hash": {"type": "string"},
                "source_commit": {"type": "string"},
                "blocking_owner": {
                    "type": "string",
                    "description": (
                        "For FAIL/INCONCLUSIVE: who should fix this. "
                        "Used by lead-review-routing to choose the rework "
                        "destination role."
                    ),
                },
                "suggested_routing": {
                    "type": "string",
                    "description": (
                        "For FAIL/INCONCLUSIVE: free-form routing hint "
                        "the lead applies (e.g., 'route to operator', "
                        "'lead move to rework for PB')."
                    ),
                },
                "evidence": {"type": "object"},
            },
            "required": ["task_id", "reviewer_role", "verdict"],
        },
    },
]


# --- Tool dispatcher ---


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "mc_task_read":
        return op_task_read(arguments["task_id"])
    if name == "mc_comment_create":
        return op_comment_create(arguments["task_id"], arguments["message"])
    if name == "mc_pipeline_event_create":
        evidence = arguments.get("evidence")
        return op_pipeline_event_create(
            arguments["task_id"],
            arguments["state"],
            source=arguments.get("source", "mc_mcp_server.py"),
            commit_sha=arguments.get("commit_sha"),
            artifact_hash=arguments.get("artifact_hash"),
            deploy_target=arguments.get("deploy_target"),
            live_sha=arguments.get("live_sha"),
            evidence=evidence if isinstance(evidence, dict) else None,
        )
    if name == "mc_review_event_create":
        evidence = arguments.get("evidence")
        return op_review_event_create(
            arguments["task_id"],
            arguments["reviewer_role"],
            arguments["verdict"],
            evidence_type=arguments.get("evidence_type"),
            target=arguments.get("target"),
            build_hash=arguments.get("build_hash"),
            source_commit=arguments.get("source_commit"),
            blocking_owner=arguments.get("blocking_owner"),
            suggested_routing=arguments.get("suggested_routing"),
            evidence=evidence if isinstance(evidence, dict) else None,
        )
    raise ValueError(f"unknown tool: {name}")


# --- JSON-RPC handlers ---


def handle_initialize(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


def handle_tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {"tools": TOOLS}


class InvalidToolParamsError(Exception):
    """Raised when tool params fail protocol validation (unknown tool name,
    missing required argument, wrong type). Mapped to JSON-RPC -32602
    Invalid params per MCP 2024-11-05."""


def handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        raise InvalidToolParamsError("tool 'name' must be a string")
    if not isinstance(arguments, dict):
        raise InvalidToolParamsError("tool 'arguments' must be an object")
    try:
        result = dispatch_tool(name, arguments)
    except HttpError as exc:
        # Business / API failure: surface to the LLM via tool result with
        # isError=true (per MCP spec), not as a JSON-RPC protocol error.
        return {
            "content": [{"type": "text", "text": f"HTTP {exc.status}: {exc.body[:1000]}"}],
            "isError": True,
        }
    except ValueError as exc:
        # dispatch_tool() raises ValueError for unknown tool names.
        # Per MCP, this is "invalid params" → JSON-RPC -32602.
        raise InvalidToolParamsError(str(exc)) from exc
    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "isError": False,
    }


HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}

_REQUEST_METHODS = frozenset(HANDLERS)
_NOTIFICATION_METHODS = frozenset({"notifications/initialized"})


def make_response(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def process_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC message; return a response dict or None for
    notifications.

    Per JSON-RPC 2.0 + MCP 2024-11-05:
    - Requests carry an ``id`` (string or number) and MUST get a response.
    - Notifications have no ``id`` and MUST NOT get a response.
    - The server distinguishes by the method's contract, not by whether
      the client included an ``id``. A request method without an ``id``
      is malformed and gets ``-32600 Invalid Request``.
    """
    method = message.get("method")
    params = message.get("params") or {}
    request_id = message.get("id")

    # Notifications: discard, never respond, even on error.
    if method in _NOTIFICATION_METHODS:
        return None

    # Request methods MUST carry id (string or number). Reject malformed.
    if not isinstance(method, str):
        return make_error(request_id, -32600, "Invalid Request: missing method")
    if method in _REQUEST_METHODS and request_id is None:
        return make_error(
            None,
            -32600,
            f"Invalid Request: method {method!r} requires an id",
        )

    handler = HANDLERS.get(method)
    if handler is None:
        return make_error(request_id, -32601, f"Method not found: {method}")

    try:
        result = handler(params if isinstance(params, dict) else {})
    except InvalidToolParamsError as exc:
        return make_error(request_id, -32602, f"Invalid params: {exc}")
    except Exception as exc:
        LOG.exception("handler %s failed", method)
        return make_error(request_id, -32603, f"Internal error: {exc}")

    return make_response(request_id, result)


def serve(stdin: Any = sys.stdin, stdout: Any = sys.stdout) -> None:
    """Read JSON-RPC requests from stdin, write responses to stdout.

    MCP stdio transport: each message is a single line of JSON. Server
    runs until stdin closes (parent process exits).
    """
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("dropped malformed json: %s", exc)
            continue
        response = process_message(message)
        if response is None:
            continue
        stdout.write(json.dumps(response) + "\n")
        stdout.flush()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("MC_MCP_LOG_LEVEL", "WARNING"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
