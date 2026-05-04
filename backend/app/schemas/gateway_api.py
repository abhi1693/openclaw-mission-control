"""Schemas for gateway passthrough API request and response payloads."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (NonEmptyStr, datetime)


class GatewaySessionMessageRequest(SQLModel):
    """Request payload for sending a message into a gateway session.

    ``interrupt_if_active`` (OpenClaw 2026.5.3+) routes through the
    ``sessions.steer`` RPC instead of plain ``chat.send`` — the gateway
    aborts active work and clears the queue before delivering, with a
    15s grace period for the prior turn to settle. Use from the operator
    UI's "stop and steer" affordance; default off keeps the legacy
    queue-and-deliver semantics.
    """

    content: NonEmptyStr
    interrupt_if_active: bool = False


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
    # Slice-6 lifecycle-projection fields. ``parent_session_key`` lets
    # operator tooling render parent→child spawn graphs.
    # ``last_status`` and ``last_lifecycle_reason`` carry whatever the
    # gateway broadcasts in the latest sessions.changed snapshot.
    # Lead next-action integration is a future slice; today these are
    # raw telemetry exposed for operator-dashboard consumption.
    parent_session_key: str | None = None
    last_status: str | None = None
    last_lifecycle_reason: str | None = None
    updated_at: datetime


class ProjectedGatewaySessionsResponse(SQLModel):
    """Response wrapper for ``/gateways/projected-sessions``."""

    sessions: list[ProjectedGatewaySession]
