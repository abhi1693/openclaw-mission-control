# ruff: noqa

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.requests import Request

from app.core import error_handling
from app.core.error_handling import (
    REQUEST_ID_HEADER,
    _error_payload,
    _get_request_id,
    _http_exception_exception_handler,
    _request_validation_exception_handler,
    _response_validation_exception_handler,
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
