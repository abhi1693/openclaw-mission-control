"""Schemas for gateway passthrough API request and response payloads."""

from __future__ import annotations

from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (NonEmptyStr,)


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
