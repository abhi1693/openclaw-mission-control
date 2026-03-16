"""Structured error payload schemas used by API responses."""

from __future__ import annotations

from pydantic import Field
from sqlmodel import SQLModel
from sqlmodel._compat import SQLModelConfig


class LLMErrorResponse(SQLModel):
    """Standardized LLM-facing error payload used by API contracts."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "title": "LLMErrorResponse",
            "x-llm-intent": "llm_error_handling",
            "x-when-to-use": [
                "Structured, tool-facing API errors for agent workflows",
                "Gateway handoff and delegated-task operations",
            ],
            "x-required-actor": "agent",
            "x-side-effects": [
                "Returns explicit machine-readable error context",
                "Includes request_id for end-to-end traceability",
            ],
        },
    )

    detail: str | dict[str, object] | list[object] = Field(
        description=(
            "Error payload. Agents should rely on `code` when present and default "
            "to `message` for fallback display."
        ),
        examples=[
            "Invalid payload for lead escalation.",
            {"code": "not_found", "message": "Agent not found."},
        ],
    )
    request_id: str | None = Field(
        default=None,
        description="Request correlation identifier injected by middleware.",
    )
    code: str | None = Field(
        default=None,
        description="Optional machine-readable error code.",
        examples=["gateway_unavailable", "dependency_validation_failed"],
    )
    retryable: bool | None = Field(
        default=None,
        description="Whether a client should retry the call after remediating transient conditions.",
    )


class BlockedTaskDetail(SQLModel):
    """Error detail payload listing blocking dependency task identifiers."""

    message: str
    code: str | None = None
    blocked_by_task_ids: list[str] = Field(default_factory=list)


class BlockedTaskError(SQLModel):
    """Top-level blocked-task error response envelope."""

    detail: BlockedTaskDetail
