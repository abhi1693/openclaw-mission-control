"""Global exception handlers and request-id middleware for FastAPI.

This module standardizes two operational behaviors:

1) **Request IDs**
   - Every response includes an `X-Request-Id` header.
   - Clients may supply their own request id; otherwise we generate one.
   - The request id is propagated into logs via context vars.

2) **Error responses**
   - Errors are returned as JSON with a stable top-level shape:
     `{ "detail": ..., "request_id": ... }`
   - Validation errors (`422`) return structured field errors.
   - Unhandled errors are logged at ERROR and return a generic 500.

Design notes:
- The request-id middleware is installed *outermost* so it runs even when other
  middleware returns early.
- Health endpoints are excluded from request logs by default to reduce noise.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import (
    TRACE_LEVEL,
    get_logger,
    reset_request_id,
    reset_request_route_context,
    set_request_id,
    set_request_route_context,
)

if TYPE_CHECKING:  # pragma: no cover
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = get_logger(__name__)

REQUEST_ID_HEADER: Final[str] = "X-Request-Id"
_HEALTH_CHECK_PATHS: Final[frozenset[str]] = frozenset({"/health", "/healthz", "/readyz"})

ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]


class RequestIdMiddleware:
    """ASGI middleware that ensures every request has a request-id."""

    def __init__(self, app: ASGIApp, *, header_name: str = REQUEST_ID_HEADER) -> None:
        """Initialize middleware with app instance and header name."""
        self._app = app
        self._header_name = header_name
        self._header_name_bytes = header_name.lower().encode("latin-1")
        self._slow_request_ms = settings.request_log_slow_ms
        self._include_health_logs = settings.request_log_include_health

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Inject request-id into request state and response headers."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = str(scope.get("method") or "UNKNOWN").upper()
        path = str(scope.get("path") or "")
        client = scope.get("client")
        client_ip: str | None = None
        if isinstance(client, tuple) and client and isinstance(client[0], str):
            client_ip = client[0]
        should_log = self._include_health_logs or path not in _HEALTH_CHECK_PATHS
        started_at = perf_counter()
        status_code: int | None = None

        request_id = self._get_or_create_request_id(scope)
        context_token = set_request_id(request_id)
        route_context_tokens = set_request_route_context(method, path)
        if should_log:
            logger.log(
                TRACE_LEVEL,
                "http.request.start",
                extra={
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                },
            )

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                # Starlette uses `list[tuple[bytes, bytes]]` here.
                headers: list[tuple[bytes, bytes]] = message.setdefault("headers", [])
                if not any(key.lower() == self._header_name_bytes for key, _ in headers):
                    request_id_bytes = request_id.encode("latin-1")
                    headers.append((self._header_name_bytes, request_id_bytes))
                status = message.get("status")
                status_code = status if isinstance(status, int) else 500
                if should_log:
                    duration_ms = int((perf_counter() - started_at) * 1000)
                    extra = {
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "client_ip": client_ip,
                    }
                    if status_code >= 500:
                        logger.error("http.request.complete", extra=extra)
                    elif status_code >= 400:
                        logger.warning("http.request.complete", extra=extra)
                    else:
                        logger.debug("http.request.complete", extra=extra)
                    if self._slow_request_ms and duration_ms >= self._slow_request_ms:
                        logger.warning(
                            "http.request.slow",
                            extra={
                                **extra,
                                "slow_threshold_ms": self._slow_request_ms,
                            },
                        )
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            if should_log and status_code is None:
                logger.warning(
                    "http.request.incomplete",
                    extra={
                        "method": method,
                        "path": path,
                        "duration_ms": int((perf_counter() - started_at) * 1000),
                        "client_ip": client_ip,
                    },
                )
            reset_request_route_context(route_context_tokens)
            reset_request_id(context_token)

    def _get_or_create_request_id(self, scope: Scope) -> str:
        # Accept a client-provided request id if present.
        request_id: str | None = None
        for key, value in scope.get("headers", []):
            if key.lower() == self._header_name_bytes:
                candidate = value.decode("latin-1").strip()
                if candidate:
                    request_id = candidate
                break

        if request_id is None:
            request_id = uuid4().hex

        # `Request.state` is backed by `scope["state"]`.
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        return request_id


def install_error_handling(app: FastAPI) -> None:
    """Install middleware and exception handlers on the FastAPI app."""
    # Important: add request-id middleware last so it's the outermost middleware.
    # This ensures it still runs even if another middleware
    # (e.g. CORS preflight) returns early.
    app.add_middleware(RequestIdMiddleware)

    app.add_exception_handler(
        RequestValidationError,
        _request_validation_exception_handler,
    )
    app.add_exception_handler(
        ResponseValidationError,
        _response_validation_exception_handler,
    )
    app.add_exception_handler(
        StarletteHTTPException,
        _http_exception_exception_handler,
    )
    app.add_exception_handler(Exception, _unhandled_exception_handler)


async def _request_validation_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    if not isinstance(exc, RequestValidationError):
        msg = "Expected RequestValidationError"
        raise TypeError(msg)
    return await _request_validation_handler(request, exc)


async def _response_validation_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    if not isinstance(exc, ResponseValidationError):
        msg = "Expected ResponseValidationError"
        raise TypeError(msg)
    return await _response_validation_handler(request, exc)


async def _http_exception_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    if not isinstance(exc, StarletteHTTPException):
        msg = "Expected StarletteHTTPException"
        raise TypeError(msg)
    return await _http_exception_handler(request, exc)


def _get_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _error_payload(*, detail: object, request_id: str | None) -> dict[str, object]:
    payload: dict[str, Any] = {"detail": _json_safe(detail)}
    if request_id:
        payload["request_id"] = request_id
    return payload


def _json_safe(value: object) -> object:
    """Return a JSON-serializable representation for error payloads."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def _request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # `RequestValidationError` is expected user input; don't log at ERROR.
    request_id = _get_request_id(request)
    return JSONResponse(
        status_code=422,
        content=_error_payload(detail=exc.errors(), request_id=request_id),
    )


async def _response_validation_handler(
    request: Request,
    exc: ResponseValidationError,
) -> JSONResponse:
    request_id = _get_request_id(request)
    logger.exception(
        "response_validation_error",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "errors": exc.errors(),
        },
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(detail="Internal Server Error", request_id=request_id),
    )


async def _http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    request_id = _get_request_id(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(detail=exc.detail, request_id=request_id),
        headers=exc.headers,
    )


async def _unhandled_exception_handler(
    request: Request,
    _exc: Exception,
) -> JSONResponse:
    request_id = _get_request_id(request)
    logger.exception(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(detail="Internal Server Error", request_id=request_id),
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )
