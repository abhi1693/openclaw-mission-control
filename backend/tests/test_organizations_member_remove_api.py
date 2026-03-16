# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

from app.api import organizations
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User
from app.services.organizations import OrganizationContext


@dataclass
class _FakeExecResult:
    first_value: Any = None
    all_values: list[Any] | None = None

    def first(self) -> Any:
        return self.first_value

    def __iter__(self):
        return iter(self.all_values or [])


@dataclass
class _FakeSession:
    exec_results: list[Any]

    executed: list[Any] = field(default_factory=list)
    deleted: list[Any] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)
    committed: int = 0

    async def exec(self, _statement: Any) -> Any:
        is_dml = _statement.__class__.__name__ in {"Delete", "Update", "Insert"}
        if is_dml:
            self.executed.append(_statement)
            return None
        if not self.exec_results:
            raise AssertionError("No more exec_results left for session.exec")
        return self.exec_results.pop(0)

    async def execute(self, statement: Any) -> None:
        self.executed.append(statement)

    async def delete(self, value: Any) -> None:
        self.deleted.append(value)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1


def _make_ctx(*, org_id: UUID, user_id: UUID, role: str) -> OrganizationContext:
    return OrganizationContext(
        organization=Organization(id=org_id, name=f"org-{org_id}"),
        member=OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=role,
        ),
    )


@pytest.mark.asyncio
async def test_remove_org_member_deletes_member_access_and_member() -> None:
    org_id = uuid4()
    member_id = uuid4()
    actor_user_id = uuid4()
    target_user_id = uuid4()
    fallback_org_id = uuid4()
    member = OrganizationMember(
        id=member_id,
        organization_id=org_id,
        user_id=target_user_id,
        role="member",
    )
    user = User(
        id=target_user_id,
        clerk_user_id="target",
        active_organization_id=org_id,
    )
    session = _FakeSession(
        exec_results=[
            _FakeExecResult(first_value=member),
            _FakeExecResult(first_value=user),
            _FakeExecResult(first_value=fallback_org_id),
        ],
    )
    ctx = _make_ctx(org_id=org_id, user_id=actor_user_id, role="admin")

    await organizations.remove_org_member(member_id=member_id, session=session, ctx=ctx)

    executed_tables = [statement.table.name for statement in session.executed]
    assert executed_tables == ["organization_board_access"]
    assert session.deleted == [member]
    assert session.committed == 1
    assert user.active_organization_id == fallback_org_id
    assert session.added == [user]


@pytest.mark.asyncio
async def test_remove_org_member_disallows_self_removal() -> None:
    org_id = uuid4()
    user_id = uuid4()
    member = OrganizationMember(
        id=uuid4(),
        organization_id=org_id,
        user_id=user_id,
        role="member",
    )
    session = _FakeSession(exec_results=[_FakeExecResult(first_value=member)])
    ctx = _make_ctx(org_id=org_id, user_id=user_id, role="owner")

    with pytest.raises(HTTPException) as exc_info:
        await organizations.remove_org_member(member_id=member.id, session=session, ctx=ctx)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert session.executed == []
    assert session.deleted == []
    assert session.committed == 0


@pytest.mark.asyncio
async def test_remove_org_member_requires_owner_to_remove_owner() -> None:
    org_id = uuid4()
    member = OrganizationMember(
        id=uuid4(),
        organization_id=org_id,
        user_id=uuid4(),
        role="owner",
    )
    session = _FakeSession(exec_results=[_FakeExecResult(first_value=member)])
    ctx = _make_ctx(org_id=org_id, user_id=uuid4(), role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await organizations.remove_org_member(member_id=member.id, session=session, ctx=ctx)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert session.executed == []
    assert session.deleted == []
    assert session.committed == 0


@pytest.mark.asyncio
async def test_remove_org_member_rejects_removing_last_owner() -> None:
    org_id = uuid4()
    member = OrganizationMember(
        id=uuid4(),
        organization_id=org_id,
        user_id=uuid4(),
        role="owner",
    )
    session = _FakeSession(
        exec_results=[
            _FakeExecResult(first_value=member),
            _FakeExecResult(all_values=[member]),
        ],
    )
    ctx = _make_ctx(org_id=org_id, user_id=uuid4(), role="owner")

    with pytest.raises(HTTPException) as exc_info:
        await organizations.remove_org_member(member_id=member.id, session=session, ctx=ctx)

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert session.executed == []
    assert session.deleted == []
    assert session.committed == 0
