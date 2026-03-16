from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.security_headers import SecurityHeadersMiddleware


@pytest.mark.asyncio
async def test_security_headers_middleware_passes_through_non_http_scope() -> None:
    called = False

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        _ = receive
        _ = send
        nonlocal called
        called = scope["type"] == "websocket"

    middleware = SecurityHeadersMiddleware(app, x_frame_options="SAMEORIGIN")
    await middleware({"type": "websocket", "headers": []}, lambda: None, lambda _: None)

    assert called is True


@pytest.mark.asyncio
async def test_security_headers_middleware_appends_lowercase_raw_header_names() -> None:
    sent_messages: list[dict[str, object]] = []

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        _ = scope
        _ = receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def capture(message):  # type: ignore[no-untyped-def]
        sent_messages.append(message)

    middleware = SecurityHeadersMiddleware(app, x_frame_options="SAMEORIGIN")
    await middleware(
        {"type": "http", "method": "GET", "path": "/", "headers": []}, lambda: None, capture
    )

    response_start = next(
        message for message in sent_messages if message.get("type") == "http.response.start"
    )
    headers = response_start.get("headers")
    assert isinstance(headers, list)
    header_names = {name for name, _value in headers}
    assert b"x-frame-options" in header_names
    assert b"X-Frame-Options" not in header_names


def test_security_headers_middleware_injects_configured_headers() -> None:
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options="nosniff",
        x_frame_options="SAMEORIGIN",
        referrer_policy="strict-origin-when-cross-origin",
        permissions_policy="camera=(), microphone=(), geolocation=()",
    )

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/ok")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_security_headers_middleware_does_not_override_existing_values() -> None:
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options="nosniff",
        x_frame_options="SAMEORIGIN",
        referrer_policy="strict-origin-when-cross-origin",
        permissions_policy="camera=(), microphone=(), geolocation=()",
    )

    @app.get("/already-set")
    def already_set(response: Response) -> dict[str, bool]:
        response.headers["X-Frame-Options"] = "ALLOWALL"
        response.headers["Referrer-Policy"] = "unsafe-url"
        return {"ok": True}

    response = TestClient(app).get("/already-set")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "ALLOWALL"
    assert response.headers["referrer-policy"] == "unsafe-url"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_security_headers_middleware_includes_headers_on_cors_preflight() -> None:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://example.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options="nosniff",
    )

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).options(
        "/ok",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"


def test_security_headers_middleware_skips_blank_config_values() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/ok")

    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") is None
    assert response.headers.get("x-frame-options") is None
    assert response.headers.get("referrer-policy") is None
    assert response.headers.get("permissions-policy") is None
