# ruff: noqa

from __future__ import annotations

import logging

import pytest

from app.core import error_handling as error_handling_module
from app.core.error_handling import REQUEST_ID_HEADER, RequestIdMiddleware
from app.core.logging import TRACE_LEVEL, AppLogFilter, get_logger
from app.core.version import APP_NAME, APP_VERSION


@pytest.mark.asyncio
async def test_request_id_middleware_passes_through_non_http_scope() -> None:
    called = False

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True

    middleware = RequestIdMiddleware(app)

    request_scope = {"type": "websocket", "headers": []}
    await middleware(request_scope, lambda: None, lambda message: None)  # type: ignore[arg-type]

    assert called is True


@pytest.mark.asyncio
async def test_request_id_middleware_ignores_blank_client_header_and_generates_one() -> None:
    captured_request_id: str | None = None
    response_headers: list[tuple[bytes, bytes]] = []

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        nonlocal captured_request_id
        captured_request_id = scope.get("state", {}).get("request_id")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):  # type: ignore[no-untyped-def]
        if message["type"] == "http.response.start":
            response_headers.extend(list(message.get("headers") or []))

    middleware = RequestIdMiddleware(app)

    request_scope = {
        "type": "http",
        "headers": [(REQUEST_ID_HEADER.lower().encode("latin-1"), b"   ")],
    }
    await middleware(request_scope, lambda: None, send)

    assert isinstance(captured_request_id, str) and captured_request_id
    # Header should reflect the generated id, not the blank one.
    values = [
        v for k, v in response_headers if k.lower() == REQUEST_ID_HEADER.lower().encode("latin-1")
    ]
    assert values == [captured_request_id.encode("latin-1")]


@pytest.mark.asyncio
async def test_request_id_middleware_does_not_duplicate_existing_header() -> None:
    sent_start = False
    start_headers: list[tuple[bytes, bytes]] | None = None

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        # Simulate an app that already sets the request id header.
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(REQUEST_ID_HEADER.lower().encode("latin-1"), b"already")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):  # type: ignore[no-untyped-def]
        nonlocal sent_start, start_headers
        if message["type"] == "http.response.start":
            sent_start = True
            start_headers = list(message.get("headers") or [])

    middleware = RequestIdMiddleware(app)

    request_scope = {"type": "http", "headers": []}
    await middleware(request_scope, lambda: None, send)

    assert sent_start is True
    assert start_headers is not None

    # Ensure the middleware did not append a second copy.
    values = [
        v for k, v in start_headers if k.lower() == REQUEST_ID_HEADER.lower().encode("latin-1")
    ]
    assert values == [b"already"]


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_request_id_middleware_logs_trace_start_and_debug_completion() -> None:
    capture = _CaptureHandler()
    capture.setLevel(TRACE_LEVEL)
    logger = error_handling_module.logger
    logger.setLevel(TRACE_LEVEL)
    logger.addHandler(capture)

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestIdMiddleware(app)
    request_scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/bootstrap",
        "client": ("127.0.0.1", 5454),
        "headers": [],
    }
    sent_messages: list[dict[str, object]] = []

    async def send(message):  # type: ignore[no-untyped-def]
        sent_messages.append(message)

    try:
        await middleware(request_scope, lambda: None, send)
    finally:
        logger.removeHandler(capture)
        capture.close()

    start = next(
        record for record in capture.records if record.getMessage() == "http.request.start"
    )
    complete = next(
        record for record in capture.records if record.getMessage() == "http.request.complete"
    )

    assert start.levelname == "TRACE"
    assert getattr(start, "method", None) == "GET"
    assert getattr(start, "path", None) == "/api/v1/auth/bootstrap"

    assert complete.levelname == "DEBUG"
    assert getattr(complete, "status_code", None) == 200
    assert isinstance(getattr(complete, "duration_ms", None), int)


@pytest.mark.asyncio
async def test_request_id_middleware_logs_error_for_5xx_completion() -> None:
    capture = _CaptureHandler()
    capture.setLevel(TRACE_LEVEL)
    logger = error_handling_module.logger
    logger.setLevel(TRACE_LEVEL)
    logger.addHandler(capture)

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"unavailable"})

    middleware = RequestIdMiddleware(app)
    request_scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/tasks",
        "client": ("127.0.0.1", 5454),
        "headers": [],
    }
    sent_messages: list[dict[str, object]] = []

    async def send(message):  # type: ignore[no-untyped-def]
        sent_messages.append(message)

    try:
        await middleware(request_scope, lambda: None, send)
    finally:
        logger.removeHandler(capture)
        capture.close()

    complete = next(
        record for record in capture.records if record.getMessage() == "http.request.complete"
    )
    assert complete.levelname == "ERROR"
    assert getattr(complete, "status_code", None) == 503


@pytest.mark.asyncio
async def test_request_id_middleware_enriches_in_request_logs_with_route_context() -> None:
    capture = _CaptureHandler()
    capture.setLevel(TRACE_LEVEL)
    capture.addFilter(AppLogFilter(APP_NAME, APP_VERSION))

    app_logger = get_logger("tests.request_context.enrichment")
    app_logger.setLevel(TRACE_LEVEL)
    app_logger.addHandler(capture)

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        app_logger.info("inside.request.handler")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestIdMiddleware(app)
    request_scope = {
        "type": "http",
        "method": "PUT",
        "path": "/api/v1/boards/abc",
        "client": ("127.0.0.1", 5454),
        "headers": [],
    }

    async def send(_message):  # type: ignore[no-untyped-def]
        return None

    try:
        await middleware(request_scope, lambda: None, send)
    finally:
        app_logger.removeHandler(capture)
        capture.close()

    record = next(item for item in capture.records if item.getMessage() == "inside.request.handler")
    assert isinstance(getattr(record, "request_id", None), str) and getattr(record, "request_id")
    assert getattr(record, "method", None) == "PUT"
    assert getattr(record, "path", None) == "/api/v1/boards/abc"
