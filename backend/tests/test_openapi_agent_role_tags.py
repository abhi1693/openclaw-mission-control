# ruff: noqa: S101
"""OpenAPI role-tag coverage for agent-facing endpoint discovery."""

from __future__ import annotations

from app.main import app


def _op_tags(schema: dict[str, object], *, path: str, method: str) -> set[str]:
    op = schema["paths"][path][method]
    return set(op.get("tags", []))


def _op_description(schema: dict[str, object], *, path: str, method: str) -> str:
    op = schema["paths"][path][method]
    return str(op.get("description", "")).strip()


def test_openapi_agent_role_tags_are_exposed() -> None:
    """Role tags should be queryable without path-based heuristics."""
    schema = app.openapi()

    assert "agent-lead" in _op_tags(
        schema,
        path="/api/v1/agent/boards/{board_id}/tasks",
        method="post",
    )
    assert "agent-worker" in _op_tags(
        schema,
        path="/api/v1/agent/boards/{board_id}/tasks",
        method="get",
    )
    assert "agent-main" in _op_tags(
        schema,
        path="/api/v1/agent/gateway/leads/broadcast",
        method="post",
    )
    assert "agent-worker" in _op_tags(
        schema,
        path="/api/v1/boards/{board_id}/group-memory",
        method="get",
    )
    assert "agent-lead" in _op_tags(
        schema,
        path="/api/v1/boards/{board_id}/group-snapshot",
        method="get",
    )
    heartbeat_tags = _op_tags(schema, path="/api/v1/agent/heartbeat", method="post")
    assert {"agent-lead", "agent-worker", "agent-main"} <= heartbeat_tags


def test_openapi_agent_role_endpoint_descriptions_exist() -> None:
    """Agent-role endpoints should provide human-readable operation guidance."""
    schema = app.openapi()

    assert _op_description(
        schema,
        path="/api/v1/agent/boards/{board_id}/tasks",
        method="post",
    )
    assert _op_description(
        schema,
        path="/api/v1/agent/boards/{board_id}/tasks/{task_id}",
        method="patch",
    )
    assert _op_description(
        schema,
        path="/api/v1/agent/heartbeat",
        method="post",
    )
    assert _op_description(
        schema,
        path="/api/v1/boards/{board_id}/group-memory",
        method="get",
    )
    assert _op_description(
        schema,
        path="/api/v1/boards/{board_id}/group-snapshot",
        method="get",
    )
