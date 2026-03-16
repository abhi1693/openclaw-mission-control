# ruff: noqa: INP001, S101
"""Regression test for board-group delete ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from app.api import board_groups
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.services.organizations import OrganizationContext


@dataclass
class _FakeSession:
    executed: list[object] = field(default_factory=list)
    committed: int = 0

    async def exec(self, statement: object) -> None:
        self.executed.append(statement)

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def commit(self) -> None:
        self.committed += 1


@pytest.mark.asyncio
async def test_delete_board_group_cleans_group_memory_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete should remove boards, memory, then the board-group record."""
    group_id = uuid4()

    async def _fake_require_group_access(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        board_groups,
        "_require_group_access",
        _fake_require_group_access,
    )

    session: Any = _FakeSession()
    org_id = uuid4()
    ctx = OrganizationContext(
        organization=Organization(id=org_id, name=f"org-{org_id}"),
        member=OrganizationMember(
            organization_id=org_id,
            user_id=uuid4(),
            role="admin",
        ),
    )

    await board_groups.delete_board_group(
        group_id=group_id,
        session=session,
        ctx=ctx,
    )

    statement_tables = [statement.table.name for statement in session.executed]
    assert statement_tables == ["boards", "board_group_memory", "board_groups"]
    assert session.committed == 1
