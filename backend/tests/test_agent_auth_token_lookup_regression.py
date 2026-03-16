# ruff: noqa: INP001
"""Regression test sketch for agent-token lookup complexity.

Context:
- Current implementation performs PBKDF2 verification in a loop over *all* agents
  that have a token hash (`agent_auth._find_agent_for_token`).
- This is O(N_agents) *and* each verify is expensive (PBKDF2 200k iterations).

This test is marked xfail to document the desired behavior after a hardening
refactor: O(1) lookup + single hash verify.

Once token lookup is refactored, flip this to a normal passing test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import agent_auth


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Known DoS risk: agent token verification is currently O(N_agents)."
    " Refactor token scheme/lookup to O(1) and make this pass.",
    strict=False,
)
async def test_agent_token_lookup_should_not_verify_more_than_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fake a session that returns many agents with token hashes.
    class _FakeSession:
        async def exec(self, _stmt: object) -> list[object]:
            agents = []
            for i in range(50):
                agents.append(
                    SimpleNamespace(agent_token_hash=f"pbkdf2_sha256$1$salt{i}$digest{i}")
                )
            return agents

    calls = {"n": 0}

    def _fake_verify(_token: str, _stored_hash: str) -> bool:
        calls["n"] += 1
        # Always invalid
        return False

    monkeypatch.setattr(agent_auth, "verify_agent_token", _fake_verify)

    out = await agent_auth._find_agent_for_token(_FakeSession(), "invalid")  # type: ignore[arg-type]
    assert out is None

    # Desired behavior after refactor: avoid linear scan.
    assert calls["n"] <= 1
