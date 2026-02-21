# ruff: noqa: INP001, S101

from __future__ import annotations

from app.main import app


def test_openapi_blocked_task_error_includes_code_field() -> None:
    schema = app.openapi()

    blocked_detail = schema["components"]["schemas"]["BlockedTaskDetail"]
    props = blocked_detail.get("properties", {})

    # `code` is optional but must be documented for clients.
    assert "code" in props
    assert props["code"].get("anyOf")
