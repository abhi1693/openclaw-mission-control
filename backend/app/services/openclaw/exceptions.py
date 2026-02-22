"""OpenClaw-specific exception definitions and mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fastapi import HTTPException, status


class GatewayOperation(str, Enum):
    """Typed gateway operations used for consistent HTTP error mapping."""

    NUDGE_AGENT = "nudge_agent"
    SOUL_READ = "soul_read"
    SOUL_WRITE = "soul_write"
    FILES_LIST = "files_list"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    ASK_USER_DISPATCH = "ask_user_dispatch"
    LEAD_MESSAGE_DISPATCH = "lead_message_dispatch"
    LEAD_BROADCAST_DISPATCH = "lead_broadcast_dispatch"
    ONBOARDING_START_DISPATCH = "onboarding_start_dispatch"
    ONBOARDING_ANSWER_DISPATCH = "onboarding_answer_dispatch"


@dataclass(frozen=True, slots=True)
class GatewayErrorPolicy:
    """HTTP policy for mapping gateway operation failures."""

    status_code: int
    detail_template: str


_GATEWAY_ERROR_POLICIES: dict[GatewayOperation, GatewayErrorPolicy] = {
    GatewayOperation.NUDGE_AGENT: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway nudge failed: {error}",
    ),
    GatewayOperation.SOUL_READ: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway SOUL read failed: {error}",
    ),
    GatewayOperation.SOUL_WRITE: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway SOUL update failed: {error}",
    ),
    GatewayOperation.FILES_LIST: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway files list failed: {error}",
    ),
    GatewayOperation.FILE_READ: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway file read failed: {error}",
    ),
    GatewayOperation.FILE_WRITE: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway file update failed: {error}",
    ),
    GatewayOperation.ASK_USER_DISPATCH: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway ask-user dispatch failed: {error}",
    ),
    GatewayOperation.LEAD_MESSAGE_DISPATCH: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway lead message dispatch failed: {error}",
    ),
    GatewayOperation.LEAD_BROADCAST_DISPATCH: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway lead broadcast dispatch failed: {error}",
    ),
    GatewayOperation.ONBOARDING_START_DISPATCH: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway onboarding start dispatch failed: {error}",
    ),
    GatewayOperation.ONBOARDING_ANSWER_DISPATCH: GatewayErrorPolicy(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail_template="Gateway onboarding answer dispatch failed: {error}",
    ),
}


def map_gateway_error_to_http_exception(
    operation: GatewayOperation,
    exc: Exception,
) -> HTTPException:
    """Map a gateway failure into a typed HTTP exception."""
    policy = _GATEWAY_ERROR_POLICIES[operation]
    return HTTPException(
        status_code=policy.status_code,
        detail=policy.detail_template.format(error=str(exc)),
    )


def map_gateway_error_message(
    operation: GatewayOperation,
    exc: Exception,
) -> str:
    """Map a gateway failure into a stable error message string."""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            return detail
        return str(detail)
    return map_gateway_error_to_http_exception(operation, exc).detail
