"""Unit tests for the Mission Control MCP server.

Validates the JSON-RPC protocol surface (initialize, tools/list,
tools/call), tool dispatch, error handling, and response shape against
the MCP 2024-11-05 spec. HTTP plumbing is exercised via stubbed
``urllib.request.urlopen`` so the tests stay fully offline.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Dynamic-import pattern matching test_mc_client.py and
# test_ingest_model_fallbacks.py.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mc_mcp_server.py"
_spec = importlib.util.spec_from_file_location("mc_mcp_server", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["mc_mcp_server"] = _module
_spec.loader.exec_module(_module)


class _StubResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_StubResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("BOARD_ID", "test-board")
    monkeypatch.setenv("MC_BASE_URL", "http://test")


# --- protocol surface ---


class TestInitialize:
    def test_returns_protocol_version_and_server_info(self) -> None:
        result = _module.handle_initialize({})
        assert result["protocolVersion"] == _module.PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == "mc-board-api"
        assert "tools" in result["capabilities"]

    def test_initialize_response_shape_via_process_message(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = _module.process_message(msg)
        assert resp is not None
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "result" in resp
        assert resp["result"]["serverInfo"]["name"] == "mc-board-api"

    def test_notifications_initialized_returns_no_response(self) -> None:
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert _module.process_message(msg) is None


class TestToolsList:
    def test_lists_all_four_mc_tools(self) -> None:
        result = _module.handle_tools_list({})
        names = {tool["name"] for tool in result["tools"]}
        assert names == {
            "mc_task_read",
            "mc_comment_create",
            "mc_pipeline_event_create",
            "mc_review_event_create",
        }

    def test_tools_have_input_schemas(self) -> None:
        result = _module.handle_tools_list({})
        for tool in result["tools"]:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"
            assert "properties" in tool["inputSchema"]

    def test_pipeline_event_schema_constrains_state_to_real_literal(self) -> None:
        result = _module.handle_tools_list({})
        pipeline_tool = next(
            t for t in result["tools"] if t["name"] == "mc_pipeline_event_create"
        )
        states = pipeline_tool["inputSchema"]["properties"]["state"]["enum"]
        assert set(states) == {
            "code_changed",
            "committed",
            "built",
            "deployed",
            "live_build_verified",
            "runtime_verified",
            "qa_ready",
            "model_fallback",
        }

    def test_review_event_schema_constrains_verdict_to_real_literal(self) -> None:
        result = _module.handle_tools_list({})
        review_tool = next(
            t for t in result["tools"] if t["name"] == "mc_review_event_create"
        )
        verdicts = review_tool["inputSchema"]["properties"]["verdict"]["enum"]
        assert set(verdicts) == {"pass", "fail", "inconclusive", "infra_blocked"}


# --- tool dispatch ---


class TestToolsCall:
    def test_unknown_tool_returns_invalid_params_error(self) -> None:
        """Per MCP 2024-11-05: unknown tool name is a protocol-level
        invalid-params error (-32602), not internal error (-32603).
        Codex 4th-pass finding #2.
        """
        msg = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
        resp = _module.process_message(msg)
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32602
        assert "Invalid params" in resp["error"]["message"]
        assert "nope" in resp["error"]["message"]

    def test_request_method_without_id_is_invalid_request(self) -> None:
        """Codex 4th-pass finding #1: tools/call without an id is
        malformed; must NOT execute the tool, must return -32600 with
        id=null, and must not hit the dispatcher.
        """
        from unittest import mock as mock_module

        with mock_module.patch.object(_module, "dispatch_tool") as fake_dispatch:
            msg = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "mc_comment_create", "arguments": {}},
            }
            resp = _module.process_message(msg)
        assert resp is not None
        assert resp["error"]["code"] == -32600
        assert resp["id"] is None
        # Dispatcher must NOT have run — otherwise we just performed a
        # write with no response, the original Codex finding.
        fake_dispatch.assert_not_called()

    def test_initialize_without_id_is_rejected(self) -> None:
        """initialize without id is malformed (it's a request, not a notification)."""
        msg = {"jsonrpc": "2.0", "method": "initialize"}
        resp = _module.process_message(msg)
        assert resp is not None
        assert resp["error"]["code"] == -32600

    def test_task_read_dispatches_via_paginated_list(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            return _StubResponse(
                json.dumps(
                    {"items": [{"id": "abc", "title": "found"}], "total": 1}
                ).encode()
            )

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            result = _module.handle_tools_call(
                {"name": "mc_task_read", "arguments": {"task_id": "abc"}}
            )

        assert result["isError"] is False
        body = json.loads(result["content"][0]["text"])
        assert body == {"id": "abc", "title": "found"}
        assert captured["auth"] == "Bearer test-token"
        assert "/tasks?limit=200&offset=0" in captured["url"]

    def test_comment_create_posts_message(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data)
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            return _StubResponse(b'{"id": "evt"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            result = _module.handle_tools_call(
                {
                    "name": "mc_comment_create",
                    "arguments": {"task_id": "t", "message": "Hello world"},
                }
            )

        assert result["isError"] is False
        assert captured["method"] == "POST"
        assert captured["payload"] == {"message": "Hello world"}

    def test_pipeline_event_create_with_model_fallback(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data)
            return _StubResponse(b"{}")

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            result = _module.handle_tools_call(
                {
                    "name": "mc_pipeline_event_create",
                    "arguments": {
                        "task_id": "t",
                        "state": "model_fallback",
                        "evidence": {
                            "from_model": "a",
                            "to_model": "b",
                            "reason": "timeout",
                        },
                    },
                }
            )

        assert result["isError"] is False
        payload = captured["payload"]
        assert payload["state"] == "model_fallback"
        assert payload["evidence"]["from_model"] == "a"

    def test_review_event_create_with_infra_blocked(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data)
            return _StubResponse(b'{"id": "rev"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            result = _module.handle_tools_call(
                {
                    "name": "mc_review_event_create",
                    "arguments": {
                        "task_id": "t",
                        "reviewer_role": "qa_e2e",
                        "verdict": "infra_blocked",
                        "evidence": {"comment": "Playwright cannot reach target"},
                    },
                }
            )

        assert result["isError"] is False
        assert captured["payload"]["verdict"] == "infra_blocked"
        assert captured["payload"]["reviewer_role"] == "qa_e2e"

    def test_review_event_create_carries_blocking_owner_and_routing(self) -> None:
        """Codex 4th-pass finding #3: the FAIL/INCONCLUSIVE routing
        fields blocking_owner and suggested_routing must be threaded
        through the MCP tool to the MC schema.
        """
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data)
            return _StubResponse(b'{"id": "rev"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            result = _module.handle_tools_call(
                {
                    "name": "mc_review_event_create",
                    "arguments": {
                        "task_id": "t",
                        "reviewer_role": "qa_e2e",
                        "verdict": "fail",
                        "blocking_owner": "PF",
                        "suggested_routing": "lead move to rework for PF",
                    },
                }
            )
        assert result["isError"] is False
        assert captured["payload"]["blocking_owner"] == "PF"
        assert (
            captured["payload"]["suggested_routing"]
            == "lead move to rework for PF"
        )

    def test_review_event_schema_advertises_blocking_owner_and_routing(self) -> None:
        """Tool input schema must list the routing fields so MCP hosts
        offer them as completion suggestions and reject typos."""
        result = _module.handle_tools_list({})
        review_tool = next(
            t for t in result["tools"] if t["name"] == "mc_review_event_create"
        )
        props = review_tool["inputSchema"]["properties"]
        assert "blocking_owner" in props
        assert "suggested_routing" in props


class TestErrorHandling:
    def test_http_error_returns_isError_true(self) -> None:
        import urllib.error

        def raise_err(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 409, "Conflict", {}, io.BytesIO(b'{"detail":"already done"}')  # type: ignore[arg-type]
            )

        with mock.patch.object(_module.urllib.request, "urlopen", raise_err):
            result = _module.handle_tools_call(
                {
                    "name": "mc_comment_create",
                    "arguments": {"task_id": "t", "message": "x"},
                }
            )

        assert result["isError"] is True
        assert "HTTP 409" in result["content"][0]["text"]
        assert "already done" in result["content"][0]["text"]

    def test_unknown_method_returns_jsonrpc_method_not_found(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 99, "method": "completely.fake.method"}
        resp = _module.process_message(msg)
        assert resp is not None
        assert resp["error"]["code"] == -32601

    def test_message_missing_method_returns_invalid_request(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 100}
        resp = _module.process_message(msg)
        assert resp is not None
        assert resp["error"]["code"] == -32600


# --- env-var resolution ---


class TestEnvResolution:
    def test_missing_token_raises_at_call_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOCAL_AUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError) as exc:
            _module.op_task_read("any")
        assert "LOCAL_AUTH_TOKEN" in str(exc.value)

    def test_missing_board_raises_at_call_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BOARD_ID", raising=False)
        with pytest.raises(RuntimeError) as exc:
            _module.op_task_read("any")
        assert "BOARD_ID" in str(exc.value)

    def test_default_base_url_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MC_BASE_URL", raising=False)
        assert _module._base_url() == _module.DEFAULT_BASE_URL


# --- stdio loop ---


class TestServeLoop:
    def test_serve_handles_initialize_and_tools_list(self) -> None:
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
        )
        stdout = io.StringIO()
        _module.serve(stdin=stdin, stdout=stdout)

        lines = [line for line in stdout.getvalue().split("\n") if line.strip()]
        assert len(lines) == 2
        first, second = (json.loads(line) for line in lines)
        assert first["id"] == 1
        assert "protocolVersion" in first["result"]
        assert second["id"] == 2
        assert len(second["result"]["tools"]) == 4

    def test_serve_skips_blank_lines_and_garbage(self) -> None:
        stdin = io.StringIO(
            "\n"
            "   \n"
            "this is not json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "initialize"}) + "\n"
        )
        stdout = io.StringIO()
        _module.serve(stdin=stdin, stdout=stdout)

        lines = [line for line in stdout.getvalue().split("\n") if line.strip()]
        # Only 1 valid response (initialize); garbage was dropped silently.
        assert len(lines) == 1
        assert json.loads(lines[0])["id"] == 5

    def test_serve_does_not_respond_to_notifications(self) -> None:
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        stdout = io.StringIO()
        _module.serve(stdin=stdin, stdout=stdout)
        # Notifications must produce zero output per JSON-RPC 2.0
        assert stdout.getvalue() == ""
