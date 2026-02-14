"""OpenAPI customization helpers.

Goal: make the generated OpenAPI spec accurately represent Mission Control auth modes.

Mission Control supports two primary auth mechanisms:
- User (Clerk): Authorization: Bearer <token> (HTTP bearer)
- Agent: X-Agent-Token: <token> (apiKey in header)

FastAPI's default OpenAPI generation only reflects dependencies that use built-in
security helpers. For agent auth, we add an explicit `AgentToken` securityScheme
and annotate operations that accept `X-Agent-Token`.

This module is intentionally *documentation-only*: it must not change runtime
authentication behavior.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi.openapi.utils import get_openapi

AGENT_TOKEN_HEADER: Final[str] = "X-Agent-Token"
AGENT_TOKEN_SCHEME_NAME: Final[str] = "AgentToken"


def _has_header_param(op: dict[str, Any], header_name: str) -> bool:
    for p in op.get("parameters", []) or []:
        if p.get("in") == "header" and p.get("name") == header_name:
            return True
    return False


def build_openapi(app_title: str, app_version: str, routes: Any) -> dict[str, Any]:
    """Return a customized OpenAPI document.

    Args:
        app_title: FastAPI app title.
        app_version: FastAPI app version.
        routes: FastAPI routes.

    Returns:
        OpenAPI dict.
    """

    schema: dict[str, Any] = get_openapi(title=app_title, version=app_version, routes=routes)

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})

    # Add AgentToken scheme (apiKey header).
    security_schemes.setdefault(
        AGENT_TOKEN_SCHEME_NAME,
        {"type": "apiKey", "in": "header", "name": AGENT_TOKEN_HEADER},
    )

    # Add a small, explicit error schema we can reference for 401/403.
    schemas = components.setdefault("schemas", {})
    schemas.setdefault(
        "HTTPError",
        {
            "title": "HTTPError",
            "type": "object",
            "properties": {"detail": {"title": "Detail", "anyOf": [{"type": "string"}, {"type": "object"}]}},
            "required": ["detail"],
            "description": "Standard FastAPI HTTPException response body.",
        },
    )

    def ensure_auth_responses(op: dict[str, Any]) -> None:
        responses = op.setdefault("responses", {})
        for code, desc in (("401", "Unauthorized"), ("403", "Forbidden")):
            responses.setdefault(
                code,
                {
                    "description": desc,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/HTTPError"},
                            "examples": {
                                "example": {"value": {"detail": desc}},
                            },
                        }
                    },
                },
            )

    # Walk operations and attach AgentToken security where relevant.
    for _path, methods in (schema.get("paths") or {}).items():
        for _method, op in (methods or {}).items():
            if not isinstance(op, dict):
                continue

            has_agent_header = _has_header_param(op, AGENT_TOKEN_HEADER)

            # If the operation already declares bearer security, and it also accepts agent token,
            # represent "either bearer OR agent token".
            if has_agent_header:
                security = op.get("security") or []
                if security:
                    # OR across entries (list). Preserve existing, add agent token as another option.
                    if not any(AGENT_TOKEN_SCHEME_NAME in s for s in security if isinstance(s, dict)):
                        security.append({AGENT_TOKEN_SCHEME_NAME: []})
                    op["security"] = security
                else:
                    op["security"] = [{AGENT_TOKEN_SCHEME_NAME: []}]

            # If the operation requires *any* auth (bearer and/or agent token), document 401/403.
            if op.get("security"):
                ensure_auth_responses(op)

    return schema
