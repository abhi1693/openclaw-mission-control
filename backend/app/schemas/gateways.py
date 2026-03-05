"""Schemas for gateway CRUD and template-sync API payloads."""

from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)
_PRIVATE_CIDRS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
)


def _is_localish_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().lower()
    if normalized in {"localhost", "host.docker.internal", "::1"}:
        return True
    try:
        parsed = ip_address(normalized)
    except ValueError:
        return False
    return any(parsed in network for network in _PRIVATE_CIDRS)


def _validate_gateway_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"ws", "wss"}:
        raise ValueError("Gateway URL must start with ws:// or wss://.")
    if not parsed.hostname:
        raise ValueError("Gateway URL must include a valid host.")
    if parsed.port is None:
        raise ValueError("Gateway URL must include an explicit port.")
    if parsed.scheme == "ws" and not _is_localish_host(parsed.hostname):
        raise ValueError(
            "Non-local gateway URLs must use wss://. Use ws:// only for localhost/private networks.",
        )
    return url.strip()


class GatewayBase(SQLModel):
    """Shared gateway fields used across create/read payloads."""

    name: str
    url: str
    workspace_root: str
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_gateway_url(value)

    @model_validator(mode="after")
    def validate_tls_policy(self) -> "GatewayBase":
        parsed = urlparse(self.url)
        if self.allow_insecure_tls and parsed.scheme != "wss":
            raise ValueError("allow_insecure_tls can only be enabled with wss:// gateway URLs.")
        if self.allow_insecure_tls and not _is_localish_host(parsed.hostname):
            raise ValueError(
                "allow_insecure_tls is only permitted for localhost/private-network gateways.",
            )
        if not (self.token or "").strip() and not _is_localish_host(parsed.hostname):
            raise ValueError("Gateway token is required for non-local gateway URLs.")
        return self


class GatewayCreate(GatewayBase):
    """Payload for creating a gateway configuration."""

    token: str | None = None

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str | None | object:
        """Normalize empty/whitespace tokens to `None`."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class GatewayUpdate(SQLModel):
    """Payload for partial gateway updates."""

    name: str | None = None
    url: str | None = None
    token: str | None = None
    workspace_root: str | None = None
    allow_insecure_tls: bool | None = None
    disable_device_pairing: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_gateway_url(value)

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str | None | object:
        """Normalize empty/whitespace tokens to `None`."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_tls_policy(self) -> "GatewayUpdate":
        if self.url and self.allow_insecure_tls:
            parsed = urlparse(self.url)
            if parsed.scheme != "wss":
                raise ValueError("allow_insecure_tls can only be enabled with wss:// gateway URLs.")
            if not _is_localish_host(parsed.hostname):
                raise ValueError(
                    "allow_insecure_tls is only permitted for localhost/private-network gateways.",
                )
        return self


class GatewayRead(GatewayBase):
    """Gateway payload returned from read endpoints."""

    id: UUID
    organization_id: UUID
    token: str | None = None
    created_at: datetime
    updated_at: datetime


class GatewayTemplatesSyncError(SQLModel):
    """Per-agent error entry from a gateway template sync operation."""

    agent_id: UUID | None = None
    agent_name: str | None = None
    board_id: UUID | None = None
    message: str


class GatewayTemplatesSyncResult(SQLModel):
    """Summary payload returned by gateway template sync endpoints."""

    gateway_id: UUID
    include_main: bool
    reset_sessions: bool
    agents_updated: int
    agents_skipped: int
    main_updated: bool
    errors: list[GatewayTemplatesSyncError] = Field(default_factory=list)
