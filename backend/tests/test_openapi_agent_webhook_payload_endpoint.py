# ruff: noqa: INP001, S101

from __future__ import annotations

from app.main import app


def test_openapi_includes_agent_webhook_payload_read_endpoint() -> None:
    schema = app.openapi()

    path = "/api/v1/agent/boards/{board_id}/webhooks/{webhook_id}/payloads/{payload_id}"
    assert path in schema["paths"]
    op = schema["paths"][path]["get"]
    tags = set(op.get("tags", []))
    assert "agent-worker" in tags
