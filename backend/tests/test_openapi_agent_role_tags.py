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


def _schema_by_name(schema: dict[str, object], name: str) -> dict[str, object]:
    return schema["components"]["schemas"][name]  # type: ignore[return-value]


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
        path="/api/v1/agent/boards",
        method="get",
    )
    health_tags = _op_tags(schema, path="/api/v1/agent/healthz", method="get")
    assert {"agent-lead", "agent-worker", "agent-main"} <= health_tags
    assert "agent-main" in _op_tags(
        schema,
        path="/api/v1/agent/boards/{board_id}",
        method="get",
    )
    assert "agent-main" in _op_tags(
        schema,
        path="/api/v1/agent/agents",
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


def test_openapi_agent_heartbeat_requires_no_request_body() -> None:
    """Authenticated heartbeats should infer identity from token without payload."""
    schema = app.openapi()
    op = schema["paths"]["/api/v1/agent/heartbeat"]["post"]
    assert "requestBody" not in op


def test_openapi_agent_tool_endpoints_include_llm_hints() -> None:
    """Tool-facing agent endpoints should expose structured usage hints and operation IDs."""
    schema = app.openapi()
    op_ids: set[str] = set()

    expected_paths = [
        ("/api/v1/agent/boards", "get"),
        ("/api/v1/agent/healthz", "get"),
        ("/api/v1/agent/boards/{board_id}", "get"),
        ("/api/v1/agent/agents", "get"),
        ("/api/v1/agent/heartbeat", "post"),
        ("/api/v1/agent/boards/{board_id}/tasks", "post"),
        ("/api/v1/agent/boards/{board_id}/tasks", "get"),
        ("/api/v1/agent/boards/{board_id}/tags", "get"),
        ("/api/v1/agent/boards/{board_id}/tasks/{task_id}", "patch"),
        ("/api/v1/agent/boards/{board_id}/tasks/{task_id}/comments", "get"),
        ("/api/v1/agent/boards/{board_id}/tasks/{task_id}/comments", "post"),
        ("/api/v1/agent/boards/{board_id}/memory", "get"),
        ("/api/v1/agent/boards/{board_id}/memory", "post"),
        ("/api/v1/boards/{board_id}/group-memory", "get"),
        ("/api/v1/boards/{board_id}/group-memory", "post"),
        ("/api/v1/boards/{board_id}/group-memory/stream", "get"),
        ("/api/v1/agent/boards/{board_id}/approvals", "get"),
        ("/api/v1/agent/boards/{board_id}/approvals", "post"),
        ("/api/v1/agent/boards/{board_id}/onboarding", "post"),
        ("/api/v1/agent/boards/{board_id}/agents/{agent_id}/soul", "get"),
        ("/api/v1/agent/agents", "post"),
        ("/api/v1/agent/boards/{board_id}/agents/{agent_id}/nudge", "post"),
        ("/api/v1/agent/boards/{board_id}/agents/{agent_id}/soul", "put"),
        ("/api/v1/agent/boards/{board_id}/agents/{agent_id}", "delete"),
        ("/api/v1/agent/boards/{board_id}/gateway/main/ask-user", "post"),
        ("/api/v1/agent/gateway/boards/{board_id}/lead/message", "post"),
        ("/api/v1/agent/gateway/leads/broadcast", "post"),
    ]
    for path, method in expected_paths:
        op = schema["paths"][path][method]
        assert "x-llm-intent" in op
        assert isinstance(op["x-llm-intent"], str)
        assert op["x-llm-intent"]
        assert "x-negative-guidance" in op
        assert isinstance(op["x-negative-guidance"], list)
        assert op["x-negative-guidance"]
        assert all(isinstance(item, str) and item for item in op["x-negative-guidance"])
        assert "x-when-to-use" in op
        assert op["x-when-to-use"]
        assert "x-routing-policy" in op
        assert op["x-routing-policy"]
        assert isinstance(op["x-routing-policy"], list)
        assert op["x-routing-policy"]
        assert all(isinstance(item, str) and item for item in op["x-routing-policy"])
        assert "x-required-actor" in op
        assert "operationId" in op
        assert isinstance(op["operationId"], str)
        assert op["operationId"]
        assert "x-routing-policy-examples" in op
        assert isinstance(op["x-routing-policy-examples"], list)
        assert op["x-routing-policy-examples"]
        assert all(
            isinstance(example, dict)
            and "decision" in example
            and "input" in example
            and isinstance(example["decision"], str)
            and example["decision"].strip()
            and isinstance(example["input"], dict)
            and "intent" in example["input"]
            and isinstance(example["input"]["intent"], str)
            and example["input"]["intent"].strip()
            for example in op["x-routing-policy-examples"]
        )
        op_ids.add(op["operationId"])
        responses = op.get("responses", {})
        assert responses
    assert len(op_ids) == len(expected_paths)


def test_openapi_agent_schemas_include_discoverability_hints() -> None:
    """Schema-level metadata should advertise usage context for model-driven tooling."""
    schema = app.openapi()

    expected_schema_hints = [
        ("AgentCreate", "agent_profile"),
        ("AgentUpdate", "agent_profile_update"),
        ("AgentRead", "agent_profile_lookup"),
        ("GatewayLeadMessageRequest", "lead_direct_message"),
        ("GatewayLeadMessageResponse", "lead_direct_message_result"),
        ("GatewayLeadBroadcastResponse", "lead_broadcast_summary"),
        ("GatewayMainAskUserRequest", "human_escalation_request"),
        ("GatewayMainAskUserResponse", "human_escalation_result"),
        ("AgentNudge", "agent_nudge"),
    ]
    for schema_name, intent in expected_schema_hints:
        component = _schema_by_name(schema, schema_name)
        assert "x-llm-intent" in component
        assert component["x-llm-intent"] == intent
        assert component.get("x-when-to-use")
        assert component.get("x-required-actor") or schema_name_is_query(schema_name)


def schema_name_is_query(schema_name: str) -> bool:
    """Some pure response shapes are actor-agnostic and expose interpretation instead."""
    return schema_name in {"GatewayLeadBroadcastResponse", "GatewayMainAskUserResponse"}


def test_openapi_agent_schema_fields_have_context() -> None:
    """Request/response fields should include field-level usage hints."""
    schema = app.openapi()

    request_schema = _schema_by_name(schema, "GatewayLeadMessageRequest")
    props = request_schema["properties"]  # type: ignore[assignment]
    assert "kind" in props
    assert props["kind"]["description"]
    assert props["kind"]["description"].startswith("Routing mode")

    nudge_schema = _schema_by_name(schema, "AgentNudge")
    nudge_props = nudge_schema["properties"]  # type: ignore[assignment]
    assert "message" in nudge_props
    assert nudge_props["message"]["description"]
