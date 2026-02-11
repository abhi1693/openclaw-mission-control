# ruff: noqa: SLF001

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core import auth
from app.core.auth_mode import AuthMode
from app.models.users import User


class _FakeSession:
    async def commit(self) -> None:  # pragma: no cover
        raise AssertionError("commit should not be called in these tests")


@pytest.mark.asyncio
async def test_get_auth_context_raises_401_when_clerk_signed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.settings, "auth_mode", AuthMode.CLERK)
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test_dummy")

    from clerk_backend_api.security.types import AuthStatus, RequestState

    async def _fake_authenticate(_request: Any) -> RequestState:
        return RequestState(status=AuthStatus.SIGNED_OUT)

    monkeypatch.setattr(auth, "_authenticate_clerk_request", _fake_authenticate)

    with pytest.raises(HTTPException) as excinfo:
        await auth.get_auth_context(  # type: ignore[arg-type]
            request=SimpleNamespace(headers={}),
            credentials=None,
            session=_FakeSession(),  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_get_auth_context_uses_request_state_payload_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.settings, "auth_mode", AuthMode.CLERK)
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test_dummy")

    from clerk_backend_api.security.types import AuthStatus, RequestState

    async def _fake_authenticate(_request: Any) -> RequestState:
        return RequestState(status=AuthStatus.SIGNED_IN, token="t", payload={"sub": "user_123"})

    async def _fake_get_or_sync_user(
        _session: Any,
        *,
        clerk_user_id: str,
        claims: dict[str, object],
    ) -> User:
        assert clerk_user_id == "user_123"
        assert claims["sub"] == "user_123"
        return User(clerk_user_id="user_123", email="user@example.com", name="User")

    async def _fake_ensure_member_for_user(_session: Any, _user: User) -> None:
        return None

    monkeypatch.setattr(auth, "_authenticate_clerk_request", _fake_authenticate)
    monkeypatch.setattr(auth, "_get_or_sync_user", _fake_get_or_sync_user)

    import app.services.organizations as orgs

    monkeypatch.setattr(orgs, "ensure_member_for_user", _fake_ensure_member_for_user)

    ctx = await auth.get_auth_context(  # type: ignore[arg-type]
        request=SimpleNamespace(headers={}),
        credentials=None,
        session=_FakeSession(),  # type: ignore[arg-type]
    )

    assert ctx.actor_type == "user"
    assert ctx.user is not None
    assert ctx.user.clerk_user_id == "user_123"


@pytest.mark.asyncio
async def test_get_auth_context_optional_returns_none_for_agent_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.settings, "auth_mode", AuthMode.CLERK)
    monkeypatch.setattr(auth.settings, "clerk_secret_key", "sk_test_dummy")

    async def _boom(_request: Any) -> Any:  # pragma: no cover
        raise AssertionError("_authenticate_clerk_request should not be called")

    monkeypatch.setattr(auth, "_authenticate_clerk_request", _boom)

    out = await auth.get_auth_context_optional(  # type: ignore[arg-type]
        request=SimpleNamespace(headers={"X-Agent-Token": "agent"}),
        credentials=None,
        session=_FakeSession(),  # type: ignore[arg-type]
    )
    assert out is None


@pytest.mark.asyncio
async def test_get_auth_context_local_mode_requires_valid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.settings, "auth_mode", AuthMode.LOCAL)
    monkeypatch.setattr(auth.settings, "local_auth_token", "expected-token")

    async def _fake_local_user(_session: Any) -> User:
        return User(clerk_user_id="local-auth-user", email="local@localhost", name="Local User")

    monkeypatch.setattr(auth, "_get_or_create_local_user", _fake_local_user)

    ctx = await auth.get_auth_context(  # type: ignore[arg-type]
        request=SimpleNamespace(headers={"Authorization": "Bearer expected-token"}),
        credentials=None,
        session=_FakeSession(),  # type: ignore[arg-type]
    )

    assert ctx.actor_type == "user"
    assert ctx.user is not None
    assert ctx.user.clerk_user_id == "local-auth-user"


@pytest.mark.asyncio
async def test_get_auth_context_optional_local_mode_returns_none_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.settings, "auth_mode", AuthMode.LOCAL)
    monkeypatch.setattr(auth.settings, "local_auth_token", "expected-token")

    async def _boom(_session: Any) -> User:  # pragma: no cover
        raise AssertionError("_get_or_create_local_user should not be called")

    monkeypatch.setattr(auth, "_get_or_create_local_user", _boom)

    out = await auth.get_auth_context_optional(  # type: ignore[arg-type]
        request=SimpleNamespace(headers={}),
        credentials=None,
        session=_FakeSession(),  # type: ignore[arg-type]
    )
    assert out is None
