"""Tests for _find_agent_for_token() prefix-filtered lookup.

FRAGILITY WARNING: These tests assert that session.exec() is called exactly twice --
once for the prefix-filtered fast path and once for the NULL-prefix fallback. If
_find_agent_for_token() is refactored to a single OR query (a valid optimization),
all tests in this module will break despite correct behavior. If you refactor the
lookup, rewrite these tests to use a real in-memory async session instead of mocks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.agent_auth import _find_agent_for_token
from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.models.agents import Agent


def _agent_with_token(token: str, *, prefix: str | None) -> Agent:
    agent = Agent(gateway_id=uuid4(), name="test")
    agent.agent_token_hash = hash_agent_token(token)
    agent.agent_token_prefix = prefix
    return agent


def _session(first_results, second_results):
    """Build a mock session returning two sequential exec() results."""
    def make_iter(items):
        mock = MagicMock()
        mock.__iter__ = lambda s: iter(items)
        return mock
    session = AsyncMock()
    session.exec = AsyncMock(side_effect=[
        make_iter(first_results),
        make_iter(second_results),
    ])
    return session


@pytest.mark.asyncio
async def test_prefix_match_returns_correct_agent():
    token = generate_agent_token()
    agent = _agent_with_token(token, prefix=token[:8])
    session = _session([agent], [])
    assert await _find_agent_for_token(session, token) is agent


@pytest.mark.asyncio
async def test_prefix_collision_pbkdf2_rejects():
    token_a = generate_agent_token()
    token_b = generate_agent_token()
    agent_b = _agent_with_token(token_b, prefix=token_a[:8])  # forced prefix collision
    session = _session([agent_b], [])
    assert await _find_agent_for_token(session, token_a) is None


@pytest.mark.asyncio
async def test_null_prefix_fallback_finds_agent():
    token = generate_agent_token()
    agent = _agent_with_token(token, prefix=None)  # pre-migration row
    session = _session([], [agent])
    assert await _find_agent_for_token(session, token) is agent


@pytest.mark.asyncio
async def test_no_match_returns_none():
    session = _session([], [])
    assert await _find_agent_for_token(session, generate_agent_token()) is None
