# ruff: noqa: SLF001

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import auth
from app.models.users import User


@dataclass
class _FakeSession:
    added: list[Any] = field(default_factory=list)
    committed: int = 0
    refreshed: list[Any] = field(default_factory=list)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, value: Any) -> None:
        self.refreshed.append(value)


def test_extract_claim_email_prefers_direct_email() -> None:
    claims: dict[str, object] = {
        "email": " User@Example.com ",
        "primary_email_address": "ignored@example.com",
    }
    assert auth._extract_claim_email(claims) == "user@example.com"


def test_extract_claim_email_from_primary_id() -> None:
    claims: dict[str, object] = {
        "primary_email_address_id": "id-2",
        "email_addresses": [
            {"id": "id-1", "email_address": "first@example.com"},
            {"id": "id-2", "email_address": "chosen@example.com"},
        ],
    }
    assert auth._extract_claim_email(claims) == "chosen@example.com"


def test_extract_claim_email_falls_back_to_first_address() -> None:
    claims: dict[str, object] = {
        "email_addresses": [
            {"id": "id-1", "email_address": "first@example.com"},
            {"id": "id-2", "email_address": "second@example.com"},
        ],
    }
    assert auth._extract_claim_email(claims) == "first@example.com"


def test_extract_claim_name_from_parts() -> None:
    claims: dict[str, object] = {
        "given_name": "Alex",
        "family_name": "Morgan",
    }
    assert auth._extract_claim_name(claims) == "Alex Morgan"


def test_extract_clerk_profile_prefers_primary_email() -> None:
    profile = SimpleNamespace(
        primary_email_address_id="e2",
        email_addresses=[
            SimpleNamespace(id="e1", email_address="first@example.com"),
            SimpleNamespace(id="e2", email_address="primary@example.com"),
        ],
        first_name="Asha",
        last_name="Rao",
    )
    email, name = auth._extract_clerk_profile(profile)
    assert email == "primary@example.com"
    assert name == "Asha"


@pytest.mark.asyncio
async def test_get_or_sync_user_updates_email_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = User(clerk_user_id="user_123", email="old@example.com", name=None)

    async def _fake_get_or_create(*_args: Any, **_kwargs: Any) -> tuple[User, bool]:
        return existing, False

    async def _fake_fetch(_clerk_user_id: str) -> tuple[str | None, str | None]:
        return "new@example.com", "New Name"

    monkeypatch.setattr(auth.crud, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(auth, "_fetch_clerk_profile", _fake_fetch)

    session = _FakeSession()
    out = await auth._get_or_sync_user(
        session,  # type: ignore[arg-type]
        clerk_user_id="user_123",
        claims={},
    )

    assert out is existing
    assert existing.email == "new@example.com"
    assert existing.name == "New Name"
    assert session.committed == 1
    assert session.refreshed == [existing]


@pytest.mark.asyncio
async def test_get_or_sync_user_uses_clerk_profile_when_claims_are_minimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = User(clerk_user_id="user_123", email=None, name=None)

    async def _fake_get_or_create(*_args: Any, **_kwargs: Any) -> tuple[User, bool]:
        return existing, False

    async def _fake_fetch(_clerk_user_id: str) -> tuple[str | None, str | None]:
        return "from-clerk@example.com", "From Clerk"

    monkeypatch.setattr(auth.crud, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(auth, "_fetch_clerk_profile", _fake_fetch)

    session = _FakeSession()
    out = await auth._get_or_sync_user(
        session,  # type: ignore[arg-type]
        clerk_user_id="user_123",
        claims={"sub": "user_123"},
    )

    assert out is existing
    assert existing.email == "from-clerk@example.com"
    assert existing.name == "From Clerk"
    assert session.committed == 1
    assert session.refreshed == [existing]


@pytest.mark.asyncio
async def test_get_or_sync_user_skips_commit_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = User(clerk_user_id="user_123", email="same@example.com", name="Name")

    async def _fake_get_or_create(*_args: Any, **_kwargs: Any) -> tuple[User, bool]:
        return existing, False

    async def _fake_fetch(_clerk_user_id: str) -> tuple[str | None, str | None]:
        return "same@example.com", "Different Name"

    monkeypatch.setattr(auth.crud, "get_or_create", _fake_get_or_create)
    monkeypatch.setattr(auth, "_fetch_clerk_profile", _fake_fetch)

    session = _FakeSession()
    out = await auth._get_or_sync_user(
        session,  # type: ignore[arg-type]
        clerk_user_id="user_123",
        claims={},
    )

    assert out is existing
    assert existing.email == "same@example.com"
    assert existing.name == "Name"
    assert session.committed == 0
    assert session.refreshed == []
