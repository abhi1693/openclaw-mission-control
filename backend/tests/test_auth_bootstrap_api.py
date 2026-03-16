# ruff: noqa: INP001
"""Unit-level API tests for /auth bootstrap endpoint.

These tests intentionally override auth dependencies to avoid DB wiring and
focus on route-handler behavior (response shape + auth gating).
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import router as auth_router
from app.core.auth import AuthContext, get_auth_context
from app.models.users import User


def _build_test_app(*, auth_ctx: AuthContext) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth_router)
    app.include_router(api_v1)

    async def _override_get_auth_context() -> AuthContext:
        return auth_ctx

    app.dependency_overrides[get_auth_context] = _override_get_auth_context
    return app


async def _get(client: AsyncClient, path: str) -> tuple[int, dict]:
    resp = await client.post(path)
    payload = resp.json() if resp.content else {}
    return resp.status_code, payload


@pytest.mark.asyncio
async def test_auth_bootstrap_returns_user_profile_when_authenticated() -> None:
    user = User(clerk_user_id="user_123", email="user@example.com", name="User")
    app = _build_test_app(auth_ctx=AuthContext(actor_type="user", user=user))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        status, payload = await _get(client, "/api/v1/auth/bootstrap")

    assert status == 200
    assert payload["clerk_user_id"] == "user_123"
    assert payload["email"] == "user@example.com"
    assert payload["name"] == "User"
    assert payload["id"]


@pytest.mark.asyncio
async def test_auth_bootstrap_rejects_requests_without_user_context() -> None:
    app = _build_test_app(auth_ctx=AuthContext(actor_type="user", user=None))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        status, payload = await _get(client, "/api/v1/auth/bootstrap")

    assert status == 401
    assert payload == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_auth_bootstrap_rejects_non_user_actor_type() -> None:
    # Runtime behavior: handler checks `auth.actor_type != "user"`.
    # Use a duck-typed object to simulate a non-user actor.
    from types import SimpleNamespace

    app = _build_test_app(
        auth_ctx=SimpleNamespace(actor_type="agent", user=None),  # type: ignore[arg-type]
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        status, payload = await _get(client, "/api/v1/auth/bootstrap")

    assert status == 401
    assert payload == {"detail": "Unauthorized"}
