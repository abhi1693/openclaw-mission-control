# ruff: noqa

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.gateway import router as gateway_router
from app.core import auth as auth_module
from app.core.auth_mode import AuthMode
from app.core.config import settings
from app.db.session import get_session
from app.services.openclaw import runtime_status


def test_extract_json_payload_tolerates_openclaw_config_warnings() -> None:
    text = """Config warnings:
- plugins.entries.openclaw-redis-agent-memory: plugin disabled
{
  "runtimeVersion": "2026.4.26",
  "taskAudit": {"errors": 6}
}
"""

    payload = runtime_status.extract_json_payload(text)

    assert payload == {
        "runtimeVersion": "2026.4.26",
        "taskAudit": {"errors": 6},
    }


@pytest.mark.asyncio
async def test_collect_openclaw_status_returns_payload_from_cli(monkeypatch) -> None:
    def _fake_run(*args, **kwargs):
        assert args[0] == ["openclaw", "status", "--json"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return SimpleNamespace(
            returncode=0,
            stdout='Config warnings:\n- disabled plugin\n{"runtimeVersion":"2026.4.26"}',
            stderr="",
        )

    monkeypatch.setattr(runtime_status.subprocess, "run", _fake_run)

    snapshot = await runtime_status.collect_openclaw_status()

    assert snapshot.ok is True
    assert snapshot.payload == {"runtimeVersion": "2026.4.26"}
    assert snapshot.error is None


@pytest.mark.asyncio
async def test_collect_openclaw_status_reports_nonzero_cli_exit(monkeypatch) -> None:
    def _fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="gateway closed",
        )

    monkeypatch.setattr(runtime_status.subprocess, "run", _fake_run)

    snapshot = await runtime_status.collect_openclaw_status()

    assert snapshot.ok is False
    assert snapshot.payload is None
    assert "gateway closed" in (snapshot.error or "")


@pytest.mark.asyncio
async def test_collect_openclaw_status_reports_os_error(monkeypatch) -> None:
    def _fake_run(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(runtime_status.subprocess, "run", _fake_run)

    snapshot = await runtime_status.collect_openclaw_status()

    assert snapshot.ok is False
    assert snapshot.payload is None
    assert "permission denied" in (snapshot.error or "")


@pytest.mark.asyncio
async def test_runtime_status_route_returns_snapshot(monkeypatch) -> None:
    import app.api.gateway as gateway_api

    async def _fake_collect_openclaw_status():
        return runtime_status.OpenClawRuntimeStatusSnapshot(
            ok=True,
            payload={"runtimeVersion": "2026.4.26"},
            return_code=0,
        )

    monkeypatch.setattr(gateway_api, "collect_openclaw_status", _fake_collect_openclaw_status)

    response = await gateway_api.openclaw_runtime_status()

    assert response.ok is True
    assert response.status == {"runtimeVersion": "2026.4.26"}
    assert response.return_code == 0


@pytest.mark.asyncio
async def test_runtime_status_route_requires_admin_auth(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_engine: AsyncEngine,
) -> None:
    unique_suffix = uuid4().hex
    monkeypatch.setattr(settings, "auth_mode", AuthMode.LOCAL)
    monkeypatch.setattr(settings, "local_auth_token", "runtime-status-token")
    monkeypatch.setattr(auth_module, "LOCAL_AUTH_USER_ID", f"runtime-status-{unique_suffix}")
    monkeypatch.setattr(auth_module, "LOCAL_AUTH_EMAIL", f"runtime-{unique_suffix}@localhost")

    async def _fake_collect_openclaw_status():
        return runtime_status.OpenClawRuntimeStatusSnapshot(
            ok=True,
            payload={"runtimeVersion": "2026.4.26"},
            return_code=0,
        )

    monkeypatch.setattr("app.api.gateway.collect_openclaw_status", _fake_collect_openclaw_status)

    session_maker = async_sessionmaker(
        sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(gateway_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[auth_module.get_session] = _override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        missing = await client.get("/api/v1/gateways/runtime/status")
        assert missing.status_code == 401

        authorized = await client.get(
            "/api/v1/gateways/runtime/status",
            headers={"Authorization": "Bearer runtime-status-token"},
        )
        assert authorized.status_code == 200
        assert authorized.json() == {
            "ok": True,
            "status": {"runtimeVersion": "2026.4.26"},
            "error": None,
            "return_code": 0,
        }
