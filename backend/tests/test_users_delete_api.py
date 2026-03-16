# ruff: noqa: S101
"""Tests for user self-delete API behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from app.api import users
from app.core.auth import AuthContext
from app.models.users import User


@dataclass
class _FakeSession:
    committed: int = 0

    async def commit(self) -> None:
        self.committed += 1


class _EmptyMembershipQuery:
    async def all(self, _session: Any) -> list[Any]:
        return []


class _FakeOrganizationMemberModel:
    class objects:
        @staticmethod
        def filter_by(**_kwargs: Any) -> _EmptyMembershipQuery:
            return _EmptyMembershipQuery()


@pytest.mark.asyncio
async def test_delete_me_aborts_when_clerk_delete_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local deletion should not run if Clerk account deletion fails."""
    session = _FakeSession()
    user = User(id=uuid4(), clerk_user_id="user_123")
    auth = AuthContext(actor_type="user", user=user)

    async def _fail_delete(_clerk_user_id: str) -> None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="clerk failure")

    async def _unexpected_update(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("crud.update_where should not be called on Clerk failure")

    async def _unexpected_delete(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("crud.delete_where should not be called on Clerk failure")

    monkeypatch.setattr(users, "delete_clerk_user", _fail_delete)
    monkeypatch.setattr(users.crud, "update_where", _unexpected_update)
    monkeypatch.setattr(users.crud, "delete_where", _unexpected_delete)

    with pytest.raises(HTTPException) as exc_info:
        await users.delete_me(session=session, auth=auth)

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert session.committed == 0


@pytest.mark.asyncio
async def test_delete_me_deletes_local_user_after_clerk_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User delete should invoke Clerk deletion, then remove local account."""
    session = _FakeSession()
    user = User(id=uuid4(), clerk_user_id="user_456")
    auth = AuthContext(actor_type="user", user=user)
    calls: dict[str, int] = {"clerk": 0, "update": 0, "delete": 0}

    async def _delete_from_clerk(clerk_user_id: str) -> None:
        assert clerk_user_id == "user_456"
        calls["clerk"] += 1

    async def _update_where(*_args: Any, **_kwargs: Any) -> int:
        calls["update"] += 1
        return 0

    async def _delete_where(*_args: Any, **_kwargs: Any) -> int:
        calls["delete"] += 1
        return 1

    monkeypatch.setattr(users, "delete_clerk_user", _delete_from_clerk)
    monkeypatch.setattr(users, "OrganizationMember", _FakeOrganizationMemberModel)
    monkeypatch.setattr(users.crud, "update_where", _update_where)
    monkeypatch.setattr(users.crud, "delete_where", _delete_where)

    response = await users.delete_me(session=session, auth=auth)

    assert response.ok is True
    assert calls["clerk"] == 1
    assert calls["update"] == 3
    assert calls["delete"] == 1
    assert session.committed == 1
