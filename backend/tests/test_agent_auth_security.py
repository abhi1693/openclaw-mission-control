# ruff: noqa: INP001, SLF001
"""Regression tests for agent-auth security hardening."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core import agent_auth
from app.core.auth import AuthContext


class _RecordingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def is_allowed(self, key: str) -> bool:
        self.keys.append(key)
        return True


async def _noop_touch(*_: object, **__: object) -> None:
    return None


@pytest.mark.asyncio
async def test_optional_agent_auth_rate_limits_bearer_agent_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    agent = SimpleNamespace(id="agent-1")
    request = SimpleNamespace(
        headers={"Authorization": "Bearer agent-secret"},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/v1/tasks/task-1"),
        method="POST",
    )

    async def _fake_find(_session: object, token: str) -> object:
        assert token == "agent-secret"
        return agent

    monkeypatch.setattr(agent_auth, "agent_auth_limiter", limiter)
    monkeypatch.setattr(agent_auth, "_find_agent_for_token", _fake_find)
    monkeypatch.setattr(agent_auth, "_touch_agent_presence", _noop_touch)

    ctx = await agent_auth.get_agent_auth_context_optional(
        request=request,  # type: ignore[arg-type]
        agent_token=None,
        authorization="Bearer agent-secret",
        session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert ctx is not None
    assert ctx.agent is agent
    assert limiter.keys == ["203.0.113.10"]


@pytest.mark.asyncio
async def test_require_user_or_agent_skips_agent_auth_when_user_auth_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(
        headers={"Authorization": "Bearer user-token"},
        client=SimpleNamespace(host="203.0.113.20"),
    )

    async def _fake_user_auth(**_: object) -> AuthContext:
        return AuthContext(actor_type="user", user=SimpleNamespace(id="user-1"))

    async def _boom_agent_auth(**_: object) -> object:
        raise AssertionError("agent auth should not run when user auth already succeeded")

    monkeypatch.setattr(deps, "get_auth_context_optional", _fake_user_auth)
    monkeypatch.setattr(deps, "get_agent_auth_context_optional", _boom_agent_auth)

    actor = await deps.require_user_or_agent(
        request=request,  # type: ignore[arg-type]
        session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert actor.actor_type == "user"
    assert actor.user is not None


@pytest.mark.asyncio
async def test_required_agent_auth_invalid_token_logs_short_prefix_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    logged: list[tuple[str, tuple[object, ...]]] = []
    request = SimpleNamespace(
        headers={"X-Agent-Token": "invalid-agent-token"},
        client=SimpleNamespace(host="203.0.113.30"),
        url=SimpleNamespace(path="/api/v1/agent/boards"),
        method="POST",
    )

    async def _fake_find(_session: object, _token: str) -> None:
        return None

    def _fake_warning(message: str, *args: object, **_: object) -> None:
        logged.append((message, args))

    monkeypatch.setattr(agent_auth, "agent_auth_limiter", limiter)
    monkeypatch.setattr(agent_auth, "_find_agent_for_token", _fake_find)
    monkeypatch.setattr(agent_auth.logger, "warning", _fake_warning)

    with pytest.raises(HTTPException) as exc_info:
        await agent_auth.get_agent_auth_context(
            request=request,  # type: ignore[arg-type]
            agent_token="invalid-agent-token",
            authorization=None,
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 401
    assert logged == [
        (
            "agent auth invalid token path=%s token_prefix=%s",
            ("/api/v1/agent/boards", "invali"),
        )
    ]


@pytest.mark.asyncio
async def test_optional_agent_auth_invalid_token_logs_short_prefix_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    logged: list[tuple[str, tuple[object, ...]]] = []
    request = SimpleNamespace(
        headers={"Authorization": "Bearer invalid-agent-token"},
        client=SimpleNamespace(host="203.0.113.40"),
        url=SimpleNamespace(path="/api/v1/tasks/task-2"),
        method="POST",
    )

    async def _fake_find(_session: object, _token: str) -> None:
        return None

    def _fake_warning(message: str, *args: object, **_: object) -> None:
        logged.append((message, args))

    monkeypatch.setattr(agent_auth, "agent_auth_limiter", limiter)
    monkeypatch.setattr(agent_auth, "_find_agent_for_token", _fake_find)
    monkeypatch.setattr(agent_auth.logger, "warning", _fake_warning)

    ctx = await agent_auth.get_agent_auth_context_optional(
        request=request,  # type: ignore[arg-type]
        agent_token=None,
        authorization="Bearer invalid-agent-token",
        session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert ctx is None
    assert logged == [
        (
            "agent auth optional invalid token path=%s token_prefix=%s",
            ("/api/v1/tasks/task-2", "invali"),
        )
    ]
