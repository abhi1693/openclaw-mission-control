"""Schemas for gateway passthrough API request and response payloads."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (NonEmptyStr, datetime)


class GatewaySessionMessageRequest(SQLModel):
    """Request payload for sending a message into a gateway session."""

    content: NonEmptyStr


class GatewayEvalApprovalResolveRequest(SQLModel):
    """Request payload for resolving an exec approval inside an eval session."""

    approval_id: NonEmptyStr
    decision: NonEmptyStr = "allow-once"


class GatewayEvalSessionEnsureRequest(SQLModel):
    """Request payload for creating/resetting an isolated eval session."""

    label: str | None = None
    reset: bool = False
    agent_id: NonEmptyStr | None = None


class GatewayResolveQuery(SQLModel):
    """Query parameters used to resolve which gateway to target."""

    board_id: str | None = None
    gateway_url: str | None = None
    gateway_token: str | None = None
    gateway_disable_device_pairing: bool | None = None
    gateway_allow_insecure_tls: bool | None = None


class GatewaysStatusResponse(SQLModel):
    """Aggregated gateway status response including session metadata."""

    connected: bool
    gateway_url: str
    sessions_count: int | None = None
    sessions: list[object] | None = None
    main_session: object | None = None
    main_session_error: str | None = None
    error: str | None = None


class GatewaySessionsResponse(SQLModel):
    """Gateway sessions list response payload."""

    sessions: list[object]
    main_session: object | None = None


class GatewaySessionResponse(SQLModel):
    """Single gateway session response payload."""

    session: object


class GatewaySessionHistoryResponse(SQLModel):
    """Gateway session history response payload."""

    history: list[object]


class GatewayCommandsResponse(SQLModel):
    """Gateway command catalog and protocol metadata."""

    protocol_version: int
    methods: list[str]
    events: list[str]


class OpenClawRuntimeStatusResponse(SQLModel):
    """Local OpenClaw runtime status snapshot."""

    ok: bool
    status: object | None = None
    error: str | None = None
    return_code: int | None = None


class ProjectedGatewaySession(SQLModel):
    """One row from the gateway_session_state projection table.

    Mirrors ``app.models.gateway_session_state.GatewaySessionState`` for
    the API surface — separate schema so MC can evolve column shape
    without breaking API consumers.
    """

    agent_id: str
    session_label: str
    session_id: str | None = None
    last_phase: str | None = None
    last_message_seq: int | None = None
    last_changed_at_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    channel: str | None = None
    aborted_last_run: bool
    updated_at: datetime


class ProjectedGatewaySessionsResponse(SQLModel):
    """Response wrapper for ``/gateways/projected-sessions``."""

    sessions: list[ProjectedGatewaySession]
