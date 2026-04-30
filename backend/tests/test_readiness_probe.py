# ruff: noqa
"""Readiness probe (`/readyz`) tests.

Verifies that the readiness endpoint actually probes the database and Redis,
returns 200 only when every dependency is healthy, and degrades to 503 with a
per-dependency `checks` map when any probe fails.

The classic /healthz liveness endpoint is intentionally unchanged — these tests
guard the new behavior added to /readyz only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _patch_db_probe(success: bool):
    """Return a patch context for the database connectivity probe.

    Replaces the `async_engine` referenced by `/readyz` with a MagicMock so the
    probe either resolves cleanly or raises, without standing up a real
    Postgres instance. We swap the whole engine binding because SQLAlchemy
    `AsyncEngine.connect` is a read-only attribute and cannot be patched
    in place.
    """

    fake_engine = MagicMock()
    if success:
        conn_mock = MagicMock()
        conn_mock.execute = AsyncMock(return_value=None)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx.__aexit__ = AsyncMock(return_value=None)
        fake_engine.connect.return_value = ctx
    else:
        fake_engine.connect.side_effect = RuntimeError("simulated database outage")
    return patch("app.main.async_engine", fake_engine)


def _patch_redis(success: bool):
    """Return a patch for the synchronous redis client used by `/readyz`."""

    client = MagicMock()
    if success:
        client.ping.return_value = True
    else:
        client.ping.side_effect = ConnectionError("simulated redis outage")
    client.close.return_value = None
    return patch("app.main.redis.Redis.from_url", return_value=client)


def test_readyz_returns_200_when_all_dependencies_are_healthy():
    with _patch_db_probe(success=True), _patch_redis(success=True):
        client = TestClient(app)
        response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "checks": {"db": "ok", "redis": "ok"}}


def test_readyz_returns_503_when_database_is_unreachable():
    with _patch_db_probe(success=False), _patch_redis(success=True):
        client = TestClient(app)
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["checks"]["db"] == "fail"
    assert body["checks"]["redis"] == "ok"


def test_readyz_returns_503_when_redis_is_unreachable():
    with _patch_db_probe(success=True), _patch_redis(success=False):
        client = TestClient(app)
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"] == "fail"


def test_readyz_reports_both_failures_independently():
    with _patch_db_probe(success=False), _patch_redis(success=False):
        client = TestClient(app)
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["checks"] == {"db": "fail", "redis": "fail"}


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_liveness_probes_remain_unconditional_200(path: str):
    """Liveness endpoints must not be coupled to dependency state."""
    with _patch_db_probe(success=False), _patch_redis(success=False):
        client = TestClient(app)
        response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
