"""FastAPI application entrypoint and router wiring for the backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi_pagination import add_pagination

from app.api.activity import router as activity_router
from app.api.agent import router as agent_router
from app.api.agents import router as agents_router
from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.board_group_memory import router as board_group_memory_router
from app.api.board_groups import router as board_groups_router
from app.api.board_memory import router as board_memory_router
from app.api.board_onboarding import router as board_onboarding_router
from app.api.board_webhooks import router as board_webhooks_router
from app.api.boards import router as boards_router
from app.api.gateway import router as gateway_router
from app.api.gateways import router as gateways_router
from app.api.machine_gateway import router as machine_gateway_router
from app.api.machines import router as machines_router
from app.api.metrics import router as metrics_router
from app.api.organizations import router as organizations_router
from app.api.skills_marketplace import router as skills_marketplace_router
from app.api.souls_directory import router as souls_directory_router
from app.api.tags import router as tags_router
from app.api.task_custom_fields import router as task_custom_fields_router
from app.api.tasks import router as tasks_router
from app.api.users import router as users_router
from app.api.platform_sync import router as platform_sync_router
from app.core.config import settings
from app.core.error_handling import install_error_handling
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.schemas.health import HealthStatusResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

configure_logging()
logger = get_logger(__name__)
OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": (
            "Authentication bootstrap endpoints for resolving caller identity and session context."
        ),
    },
    {
        "name": "health",
        "description": (
            "Service liveness/readiness probes used by infrastructure and runtime checks."
        ),
    },
    {
        "name": "agents",
        "description": "Organization-level agent directory, lifecycle, and management operations.",
    },
    {
        "name": "activity",
        "description": "Activity feed and audit timeline endpoints across boards and operations.",
    },
    {
        "name": "gateways",
        "description": "Gateway management, synchronization, and runtime control operations.",
    },
    {
        "name": "machines",
        "description": "Machine fleet registration, token management, and status tracking.",
    },
    {
        "name": "machine-gateway",
        "description": "WebSocket endpoints for machine gateway dial-home connections.",
    },
    {
        "name": "metrics",
        "description": "Aggregated operational and board analytics metrics endpoints.",
    },
    {
        "name": "organizations",
        "description": "Organization profile, membership, and governance management endpoints.",
    },
    {
        "name": "souls-directory",
        "description": "Directory and lookup endpoints for agent soul templates and variants.",
    },
    {
        "name": "skills",
        "description": "Skills marketplace, install, uninstall, and synchronization endpoints.",
    },
    {
        "name": "board-groups",
        "description": "Board group CRUD, assignment, and grouping workflow endpoints.",
    },
    {
        "name": "board-group-memory",
        "description": "Shared memory endpoints scoped to board groups and grouped boards.",
    },
    {
        "name": "boards",
        "description": "Board lifecycle, configuration, and board-level management endpoints.",
    },
    {
        "name": "board-memory",
        "description": "Board-scoped memory read/write endpoints for persistent context.",
    },
    {
        "name": "board-webhooks",
        "description": "Board webhook registration, delivery config, and lifecycle endpoints.",
    },
    {
        "name": "board-onboarding",
        "description": "Board onboarding state, setup actions, and onboarding workflow endpoints.",
    },
    {
        "name": "approvals",
        "description": "Approval request, review, and status-tracking operations for board tasks.",
    },
    {
        "name": "tasks",
        "description": "Task CRUD, dependency management, and task workflow operations.",
    },
    {
        "name": "custom-fields",
        "description": "Organization custom-field definitions and board assignment endpoints.",
    },
    {
        "name": "tags",
        "description": "Tag catalog and task-tag association management endpoints.",
    },
    {
        "name": "users",
        "description": "User profile read/update operations and user-centric settings endpoints.",
    },
    {
        "name": "agent",
        "description": (
            "Agent-scoped API surface. All endpoints require `X-Agent-Token` and are "
            "constrained by agent board access policies."
        ),
    },
    {
        "name": "agent-lead",
        "description": (
            "Lead workflows: delegation, review orchestration, approvals, and "
            "coordination actions."
        ),
    },
    {
        "name": "agent-worker",
        "description": (
            "Worker workflows: task execution, task comments, and board/group context "
            "reads/writes used during heartbeat loops."
        ),
    },
    {
        "name": "agent-main",
        "description": (
            "Gateway-main control workflows that message board leads or broadcast "
            "coordination requests."
        ),
    },
]

_JSON_SCHEMA_REF_PREFIX = "#/components/schemas/"
_OPENAPI_EXAMPLE_TAGS = {
    "agents",
    "activity",
    "gateways",
    "metrics",
    "organizations",
    "souls-directory",
    "skills",
    "board-groups",
    "board-group-memory",
    "boards",
    "board-memory",
    "board-webhooks",
    "board-onboarding",
    "approvals",
    "tasks",
    "custom-fields",
    "tags",
    "users",
}
_GENERIC_RESPONSE_DESCRIPTIONS = {"Successful Response", "Validation Error"}
_HTTP_RESPONSE_DESCRIPTIONS = {
    "200": "Request completed successfully.",
    "201": "Resource created successfully.",
    "202": "Request accepted for processing.",
    "204": "Request completed successfully with no response body.",
    "400": "Request validation failed.",
    "401": "Authentication is required or token is invalid.",
    "403": "Caller is authenticated but not authorized for this operation.",
    "404": "Requested resource was not found.",
    "409": "Request conflicts with the current resource state.",
    "422": "Request payload failed schema or field validation.",
    "429": "Request was rate-limited.",
    "500": "Internal server error.",
}
_METHOD_SUMMARY_PREFIX = {
    "get": "List",
    "post": "Create",
    "put": "Replace",
    "patch": "Update",
    "delete": "Delete",
}


def _resolve_schema_ref(
    schema: dict[str, Any],
    *,
    components: dict[str, Any],
    seen_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve local component refs for OpenAPI schema traversal."""
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith(_JSON_SCHEMA_REF_PREFIX):
        return schema
    if seen_refs is None:
        seen_refs = set()
    if ref in seen_refs:
        return schema
    seen_refs.add(ref)
    schema_name = ref[len(_JSON_SCHEMA_REF_PREFIX) :]
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return schema
    target = schemas.get(schema_name)
    if not isinstance(target, dict):
        return schema
    return _resolve_schema_ref(target, components=components, seen_refs=seen_refs)


def _example_from_schema(schema: dict[str, Any], *, components: dict[str, Any]) -> Any:
    """Generate an OpenAPI example from schema metadata with sensible fallbacks."""
    resolved = _resolve_schema_ref(schema, components=components)

    if "example" in resolved:
        return resolved["example"]
    examples = resolved.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]

    for composite_key in ("anyOf", "oneOf", "allOf"):
        composite = resolved.get(composite_key)
        if isinstance(composite, list):
            for branch in composite:
                if not isinstance(branch, dict):
                    continue
                branch_example = _example_from_schema(branch, components=components)
                if branch_example is not None:
                    return branch_example

    enum_values = resolved.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    schema_type = resolved.get("type")
    if schema_type == "object":
        output: dict[str, Any] = {}
        properties = resolved.get("properties")
        if isinstance(properties, dict):
            for key, property_schema in properties.items():
                if not isinstance(property_schema, dict):
                    continue
                property_example = _example_from_schema(property_schema, components=components)
                if property_example is not None:
                    output[key] = property_example
        if output:
            return output
        additional_properties = resolved.get("additionalProperties")
        if isinstance(additional_properties, dict):
            value_example = _example_from_schema(additional_properties, components=components)
            if value_example is not None:
                return {"key": value_example}
        return {}

    if schema_type == "array":
        items = resolved.get("items")
        if isinstance(items, dict):
            item_example = _example_from_schema(items, components=components)
            if item_example is not None:
                return [item_example]
        return []

    if schema_type == "string":
        return "string"
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "boolean":
        return False

    return None


def _inject_json_content_example(
    *,
    content: dict[str, Any],
    components: dict[str, Any],
) -> None:
    """Attach an example to application/json content when one is missing."""
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        return
    if "example" in app_json or "examples" in app_json:
        return
    schema = app_json.get("schema")
    if not isinstance(schema, dict):
        return
    generated_example = _example_from_schema(schema, components=components)
    if generated_example is not None:
        app_json["example"] = generated_example


def _build_operation_summary(*, method: str, path: str) -> str:
    """Build a readable summary when an operation does not define one."""
    prefix = _METHOD_SUMMARY_PREFIX.get(method.lower(), "Handle")
    path_without_prefix = path.removeprefix("/api/v1/")
    parts = [
        part.replace("-", " ")
        for part in path_without_prefix.split("/")
        if part and not (part.startswith("{") and part.endswith("}"))
    ]
    if not parts:
        return prefix
    return f"{prefix} {' '.join(parts)}".strip().title()


def _normalize_operation_docs(
    *,
    operation: dict[str, Any],
    method: str,
    path: str,
) -> None:
    """Normalize summary/description/responses/request-body docs for tagged operations."""
    summary = str(operation.get("summary", "")).strip()
    if not summary:
        summary = _build_operation_summary(method=method, path=path)
        operation["summary"] = summary

    description = str(operation.get("description", "")).strip()
    if not description:
        operation["description"] = f"{summary}."

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        if not str(request_body.get("description", "")).strip():
            request_body["description"] = "JSON request payload."

    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return
    for status_code, response in responses.items():
        if not isinstance(response, dict):
            continue
        existing_description = str(response.get("description", "")).strip()
        if not existing_description or existing_description in _GENERIC_RESPONSE_DESCRIPTIONS:
            response["description"] = _HTTP_RESPONSE_DESCRIPTIONS.get(
                str(status_code),
                "Request processed.",
            )


def _inject_tagged_operation_openapi_docs(openapi_schema: dict[str, Any]) -> None:
    """Ensure targeted-tag operations expose consistent OpenAPI docs and examples."""
    components = openapi_schema.get("components")
    if not isinstance(components, dict):
        return
    paths = openapi_schema.get("paths")
    if not isinstance(paths, dict):
        return

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags")
            if not isinstance(tags, list):
                continue
            if not _OPENAPI_EXAMPLE_TAGS.intersection(tags):
                continue

            _normalize_operation_docs(operation=operation, method=method, path=path)

            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                request_content = request_body.get("content")
                if isinstance(request_content, dict):
                    _inject_json_content_example(content=request_content, components=components)

            responses = operation.get("responses")
            if isinstance(responses, dict):
                for response in responses.values():
                    if not isinstance(response, dict):
                        continue
                    response_content = response.get("content")
                    if isinstance(response_content, dict):
                        _inject_json_content_example(
                            content=response_content, components=components
                        )


def _build_custom_openapi(fastapi_app: FastAPI) -> dict[str, Any]:
    """Generate OpenAPI schema with normalized docs/examples for targeted tags."""
    if fastapi_app.openapi_schema:
        return fastapi_app.openapi_schema
    openapi_schema = get_openapi(
        title=fastapi_app.title,
        version=fastapi_app.version,
        openapi_version=fastapi_app.openapi_version,
        description=fastapi_app.description,
        routes=fastapi_app.routes,
        tags=fastapi_app.openapi_tags,
        servers=fastapi_app.servers,
    )
    _inject_tagged_operation_openapi_docs(openapi_schema)
    fastapi_app.openapi_schema = openapi_schema
    return fastapi_app.openapi_schema


class MissionControlFastAPI(FastAPI):
    """FastAPI application with custom OpenAPI normalization."""

    def openapi(self) -> dict[str, Any]:
        return _build_custom_openapi(self)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize application resources before serving requests."""
    logger.info(
        "app.lifecycle.starting environment=%s db_auto_migrate=%s",
        settings.environment,
        settings.db_auto_migrate,
    )
    await init_db()
    logger.info("app.lifecycle.started")
    try:
        yield
    finally:
        logger.info("app.lifecycle.stopped")


app = MissionControlFastAPI(
    title="Mission Control API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count", "X-Limit", "X-Offset"],
    )
    logger.info("app.cors.enabled origins_count=%s", len(origins))
else:
    logger.info("app.cors.disabled")

install_error_handling(app)


@app.get(
    "/health",
    tags=["health"],
    response_model=HealthStatusResponse,
    summary="Health Check",
    description="Lightweight liveness probe endpoint.",
    responses={
        status.HTTP_200_OK: {
            "description": "Service is alive.",
            "content": {"application/json": {"example": {"ok": True}}},
        }
    },
)
def health() -> HealthStatusResponse:
    """Lightweight liveness probe endpoint."""
    return HealthStatusResponse(ok=True)


@app.get(
    "/healthz",
    tags=["health"],
    response_model=HealthStatusResponse,
    summary="Health Alias Check",
    description="Alias liveness probe endpoint for platform compatibility.",
    responses={
        status.HTTP_200_OK: {
            "description": "Service is alive.",
            "content": {"application/json": {"example": {"ok": True}}},
        }
    },
)
def healthz() -> HealthStatusResponse:
    """Alias liveness probe endpoint for platform compatibility."""
    return HealthStatusResponse(ok=True)


@app.get(
    "/readyz",
    tags=["health"],
    response_model=HealthStatusResponse,
    summary="Readiness Check",
    description="Readiness probe endpoint for service orchestration checks.",
    responses={
        status.HTTP_200_OK: {
            "description": "Service is ready.",
            "content": {"application/json": {"example": {"ok": True}}},
        }
    },
)
def readyz() -> HealthStatusResponse:
    """Readiness probe endpoint for service orchestration checks."""
    return HealthStatusResponse(ok=True)


api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth_router)
api_v1.include_router(agent_router)
api_v1.include_router(agents_router)
api_v1.include_router(activity_router)
api_v1.include_router(gateway_router)
api_v1.include_router(gateways_router)
api_v1.include_router(machine_gateway_router)
api_v1.include_router(machines_router)
api_v1.include_router(metrics_router)
api_v1.include_router(organizations_router)
api_v1.include_router(souls_directory_router)
api_v1.include_router(skills_marketplace_router)
api_v1.include_router(board_groups_router)
api_v1.include_router(board_group_memory_router)
api_v1.include_router(boards_router)
api_v1.include_router(board_memory_router)
api_v1.include_router(board_webhooks_router)
api_v1.include_router(board_onboarding_router)
api_v1.include_router(approvals_router)
api_v1.include_router(tasks_router)
api_v1.include_router(task_custom_fields_router)
api_v1.include_router(tags_router)
api_v1.include_router(users_router)
api_v1.include_router(platform_sync_router)
app.include_router(api_v1)

add_pagination(app)
logger.debug("app.routes.registered count=%s", len(app.routes))
