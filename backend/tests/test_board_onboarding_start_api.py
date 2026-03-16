# ruff: noqa: INP001, S101
"""Tests for board onboarding start-session restart behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.api import board_onboarding
from app.core.time import utcnow
from app.models.board_onboarding import BoardOnboardingSession
from app.schemas.board_onboarding import BoardOnboardingStart


@dataclass
class _FakeScalarResult:
    value: object | None

    def first(self) -> object | None:
        return self.value


@dataclass
class _FakeSession:
    first_value: object | None
    added: list[object] = field(default_factory=list)
    committed: int = 0
    refreshed: list[object] = field(default_factory=list)

    async def exec(self, _statement: object) -> _FakeScalarResult:
        return _FakeScalarResult(self.first_value)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


@pytest.mark.asyncio
async def test_start_onboarding_redispatches_when_last_message_is_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    onboarding = BoardOnboardingSession(
        board_id=board_id,
        session_key="session-key",
        status="active",
        messages=[
            {
                "role": "user",
                "content": "I prefer concise updates.",
                "timestamp": utcnow().isoformat(),
            },
        ],
    )
    session: Any = _FakeSession(first_value=onboarding)
    board = SimpleNamespace(id=board_id, name="Roadmap", description="Build v1")
    captured_calls: list[dict[str, object]] = []

    class _FakeMessagingService:
        def __init__(self, _session: object) -> None:
            self._session = _session

        async def dispatch_answer(
            self,
            *,
            board: object,
            onboarding: object,
            answer_text: str,
            correlation_id: str,
        ) -> None:
            captured_calls.append(
                {
                    "board": board,
                    "onboarding": onboarding,
                    "answer_text": answer_text,
                    "correlation_id": correlation_id,
                },
            )

    monkeypatch.setattr(
        board_onboarding,
        "BoardOnboardingMessagingService",
        _FakeMessagingService,
    )

    before = onboarding.updated_at
    result = await board_onboarding.start_onboarding(
        _payload=BoardOnboardingStart(),
        board=board,
        session=session,
    )

    assert result is onboarding
    assert len(captured_calls) == 1
    assert captured_calls[0]["answer_text"] == "I prefer concise updates."
    assert str(captured_calls[0]["correlation_id"]).startswith("onboarding.resume:")
    assert onboarding.updated_at >= before
    assert session.added == [onboarding]
    assert session.committed == 1
    assert session.refreshed == [onboarding]


@pytest.mark.asyncio
async def test_start_onboarding_does_not_redispatch_when_waiting_for_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    onboarding = BoardOnboardingSession(
        board_id=board_id,
        session_key="session-key",
        status="active",
        messages=[
            {
                "role": "user",
                "content": "I prefer concise updates.",
                "timestamp": utcnow().isoformat(),
            },
            {
                "role": "assistant",
                "content": '{"question":"What is your timezone?","options":[{"id":"1","label":"UTC"}]}',
                "timestamp": utcnow().isoformat(),
            },
        ],
    )
    session: Any = _FakeSession(first_value=onboarding)
    board = SimpleNamespace(id=board_id, name="Roadmap", description="Build v1")
    captured_calls: list[dict[str, object]] = []

    class _FakeMessagingService:
        def __init__(self, _session: object) -> None:
            self._session = _session

        async def dispatch_answer(
            self,
            *,
            board: object,
            onboarding: object,
            answer_text: str,
            correlation_id: str,
        ) -> None:
            captured_calls.append(
                {
                    "board": board,
                    "onboarding": onboarding,
                    "answer_text": answer_text,
                    "correlation_id": correlation_id,
                },
            )

    monkeypatch.setattr(
        board_onboarding,
        "BoardOnboardingMessagingService",
        _FakeMessagingService,
    )

    result = await board_onboarding.start_onboarding(
        _payload=BoardOnboardingStart(),
        board=board,
        session=session,
    )

    assert result is onboarding
    assert captured_calls == []
    assert session.added == []
    assert session.committed == 0
    assert session.refreshed == []
