# ruff: noqa

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.requests import Request

from app.core import error_handling
from app.core.error_handling import (
    REQUEST_ID_HEADER,
    _error_payload,
    _get_request_id,
    _http_exception_exception_handler,
    _json_safe,
    _request_validation_exception_handler,
    _request_validation_handler,
    _response_validation_exception_handler,
    _response_validation_handler,
    install_error_handling,
)


def test_request_validation_error_includes_request_id():
    app = FastAPI()
    install_error_handling(app)

    @app.get("/needs-int")
    def needs_int(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    resp = client.get("/needs-int?limit=abc")

    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body.get("detail"), list)
    assert isinstance(body.get("request_id"), str) and body["request_id"]
    assert resp.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_request_validation_error_handles_bytes_input_without_500():
    class Payload(BaseModel):
        content: str

    app = FastAPI()
    install_error_handling(app)

    @app.put("/needs-object")
    def needs_object(payload: Payload) -> dict[str, str]:
        return {"content": payload.content}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put(
        "/needs-object",
        content=b"plain-text-body",
        headers={"content-type": "text/plain"},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body.get("detail"), list)
    assert isinstance(body.get("request_id"), str) and body["request_id"]
    assert resp.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_http_exception_includes_request_id():
    app = FastAPI()
    install_error_handling(app)

    @app.get("/nope")
    def nope() -> None:
        raise HTTPException(status_code=404, detail="nope")

    client = TestClient(app)
    resp = client.get("/nope")

    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "nope"
    assert isinstance(body.get("request_id"), str) and body["request_id"]
    assert resp.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_unhandled_exception_returns_500_with_request_id():
    app = FastAPI()
    install_error_handling(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal Server Error"
    assert isinstance(body.get("request_id"), str) and body["request_id"]
    assert resp.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_response_validation_error_returns_500_with_request_id():
    class Out(BaseModel):
        name: str = Field(min_length=1)

    app = FastAPI()
    install_error_handling(app)

    @app.get("/bad", response_model=Out)
    def bad() -> dict[str, str]:
        return {"name": ""}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/bad")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal Server Error"
    assert isinstance(body.get("request_id"), str) and body["request_id"]
    assert resp.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_client_provided_request_id_is_preserved():
    app = FastAPI()
    install_error_handling(app)

    @app.get("/needs-int")
    def needs_int(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    resp = client.get("/needs-int?limit=abc", headers={REQUEST_ID_HEADER: "  req-123  "})

    assert resp.status_code == 422
    body = resp.json()
    assert body["request_id"] == "req-123"
    assert resp.headers.get(REQUEST_ID_HEADER) == "req-123"


def test_slow_request_emits_slow_log(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    def _fake_warning(message: str, *args: object, **kwargs: object) -> None:
        _ = args
        extra = kwargs.get("extra")
        warnings.append((message, extra if isinstance(extra, dict) else {}))

    perf_ticks = iter((100.0, 100.2))

    def _fake_perf_counter() -> float:
        return next(perf_ticks)

    monkeypatch.setattr(error_handling.settings, "request_log_slow_ms", 1)
    monkeypatch.setattr(error_handling, "perf_counter", _fake_perf_counter)
    monkeypatch.setattr(error_handling.logger, "warning", _fake_warning)

    app = FastAPI()
    install_error_handling(app)

    @app.get("/slow")
    def slow() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(app)
    resp = client.get("/slow")

    assert resp.status_code == 200
    assert any(
        message == "http.request.slow" and extra.get("slow_threshold_ms") == 1
        for message, extra in warnings
    )


def test_health_route_skips_request_logs_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(error_handling.settings, "request_log_include_health", False)

    app = FastAPI()
    install_error_handling(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert isinstance(resp.headers.get(REQUEST_ID_HEADER), str)


def test_get_request_id_returns_none_for_missing_or_invalid_state() -> None:
    # Empty state
    req = Request({"type": "http", "headers": [], "state": {}})
    assert _get_request_id(req) is None

    # Non-string request_id
    req = Request({"type": "http", "headers": [], "state": {"request_id": 123}})
    assert _get_request_id(req) is None

    # Empty string request_id
    req = Request({"type": "http", "headers": [], "state": {"request_id": ""}})
    assert _get_request_id(req) is None


def test_error_payload_omits_request_id_when_none() -> None:
    assert _error_payload(detail="x", request_id=None) == {"detail": "x"}


def test_json_safe_handles_binary_inputs() -> None:
    assert _json_safe(b"\xf0\x9f\x92\xa1") == "💡"
    assert _json_safe(bytearray(b"hello")) == "hello"
    assert _json_safe(memoryview(b"world")) == "world"


def test_json_safe_replaces_invalid_utf8_bytes() -> None:
    # Invalid UTF-8 should be replaced with U+FFFD, not crash error handling.
    assert _json_safe(b"\xff") == "\ufffd"
    assert _json_safe(bytearray(b"\xff")) == "\ufffd"
    assert _json_safe(memoryview(b"\xff")) == "\ufffd"


def test_json_safe_falls_back_to_string_for_unknown_objects() -> None:
    class Weird:
        def __str__(self) -> str:
            return "weird-value"

    assert _json_safe(Weird()) == "weird-value"


@pytest.mark.asyncio
async def test_request_validation_exception_wrapper_rejects_wrong_exception() -> None:
    req = Request({"type": "http", "headers": [], "state": {}})
    with pytest.raises(TypeError, match="Expected RequestValidationError"):
        await _request_validation_exception_handler(req, Exception("x"))


@pytest.mark.asyncio
async def test_response_validation_exception_wrapper_rejects_wrong_exception() -> None:
    req = Request({"type": "http", "headers": [], "state": {}})
    with pytest.raises(TypeError, match="Expected ResponseValidationError"):
        await _response_validation_exception_handler(req, Exception("x"))


@pytest.mark.asyncio
async def test_http_exception_wrapper_rejects_wrong_exception() -> None:
    req = Request({"type": "http", "headers": [], "state": {}})
    with pytest.raises(TypeError, match="Expected StarletteHTTPException"):
        await _http_exception_exception_handler(req, Exception("x"))


@pytest.mark.asyncio
async def test_request_validation_handler_includes_request_id() -> None:
    req = Request({"type": "http", "headers": [], "state": {"request_id": "req-1"}})
    exc = RequestValidationError(
        [
            {
                "loc": ("query", "limit"),
                "msg": "value is not a valid integer",
                "type": "type_error.integer",
            }
        ]
    )

    resp = await _request_validation_handler(req, exc)
    assert resp.status_code == 422
    assert resp.body


@pytest.mark.asyncio
async def test_request_validation_exception_wrapper_success_path() -> None:
    req = Request({"type": "http", "headers": [], "state": {"request_id": "req-wrap-1"}})
    exc = RequestValidationError(
        [
            {
                "loc": ("query", "limit"),
                "msg": "value is not a valid integer",
                "type": "type_error.integer",
            }
        ]
    )

    resp = await _request_validation_exception_handler(req, exc)
    assert resp.status_code == 422
    assert b"request_id" in resp.body


@pytest.mark.asyncio
async def test_response_validation_handler_includes_request_id() -> None:
    req = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": [],
            "state": {"request_id": "req-2"},
        }
    )
    exc = ResponseValidationError(
        [
            {
                "loc": ("response", "name"),
                "msg": "field required",
                "type": "value_error.missing",
            }
        ]
    )

    resp = await _response_validation_handler(req, exc)
    assert resp.status_code == 500
    assert resp.body


@pytest.mark.asyncio
async def test_response_validation_exception_wrapper_success_path() -> None:
    req = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": [],
            "state": {"request_id": "req-wrap-2"},
        }
    )
    exc = ResponseValidationError(
        [
            {
                "loc": ("response", "name"),
                "msg": "field required",
                "type": "value_error.missing",
            }
        ]
    )

    resp = await _response_validation_exception_handler(req, exc)
    assert resp.status_code == 500
    assert b"request_id" in resp.body
