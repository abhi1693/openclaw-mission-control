from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.boards import Board
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.organization_invites import OrganizationInvite
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User
from app.schemas.organizations import OrganizationBoardAccessSpec, OrganizationMemberAccessUpdate
from app.services import organizations


@dataclass
class _FakeExecResult:
    """Mimics the minimal SQLModel result API used in services."""

    first_value: Any = None
    all_values: list[Any] | None = None
    one_value: Any = None

    def first(self) -> Any:
        return self.first_value

    def one(self) -> Any:
        return self.one_value

    def __iter__(self):
        # Some code casts exec result to list() directly.
        return iter(self.all_values or [])


@dataclass
class _FakeSession:
    exec_results: list[Any]
    get_results: dict[tuple[type[Any], Any], Any] = field(default_factory=dict)

    added: list[Any] = field(default_factory=list)
    added_all: list[list[Any]] = field(default_factory=list)
    executed: list[Any] = field(default_factory=list)

    committed: int = 0
    flushed: int = 0
    refreshed: list[Any] = field(default_factory=list)

    async def exec(self, _statement: Any) -> Any:
        if not self.exec_results:
            raise AssertionError("No more exec_results left for session.exec")
        return self.exec_results.pop(0)

    async def execute(self, statement: Any) -> None:
        self.executed.append(statement)

    def add(self, value: Any) -> None:
        self.added.append(value)

    def add_all(self, values: list[Any]) -> None:
        self.added_all.append(values)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, value: Any) -> None:
        self.refreshed.append(value)

    async def get(self, model: type[Any], key: Any) -> Any:
        return self.get_results.get((model, key))


def test_normalize_invited_email_strips_and_lowercases() -> None:
    assert organizations.normalize_invited_email("  Foo@Example.com  ") == "foo@example.com"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" ADMIN ", "admin"),
        ("", "member"),
        ("  ", "member"),
    ],
)
def test_normalize_role(value: str, expected: str) -> None:
    assert organizations.normalize_role(value) == expected


def test_role_rank_unknown_role_falls_back_to_member_rank() -> None:
    assert organizations._role_rank("madeup") == 0
    assert organizations._role_rank(None) == 0


def test_is_org_admin_owner_admin_member() -> None:
    assert organizations.is_org_admin(OrganizationMember(organization_id=uuid4(), user_id=uuid4(), role="owner"))
    assert organizations.is_org_admin(OrganizationMember(organization_id=uuid4(), user_id=uuid4(), role="admin"))
    assert not organizations.is_org_admin(
        OrganizationMember(organization_id=uuid4(), user_id=uuid4(), role="member")
    )


@pytest.mark.asyncio
async def test_ensure_member_for_user_returns_existing_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(clerk_user_id="u1")
    existing = OrganizationMember(organization_id=uuid4(), user_id=user.id, role="member")

    async def _fake_get_active(_session: Any, _user: User) -> OrganizationMember:
        return existing

    monkeypatch.setattr(organizations, "get_active_membership", _fake_get_active)

    session = _FakeSession(exec_results=[])
    out = await organizations.ensure_member_for_user(session, user)
    assert out is existing


@pytest.mark.asyncio
async def test_ensure_member_for_user_accepts_pending_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = uuid4()
    invite = OrganizationInvite(
        organization_id=org_id,
        invited_email="a@example.com",
        token="t",
        role="member",
    )
    user = User(clerk_user_id="u1", email="a@example.com")

    async def _fake_get_active(_session: Any, _user: User) -> None:
        return None

    async def _fake_find(_session: Any, _email: str) -> OrganizationInvite:
        return invite

    accepted = OrganizationMember(organization_id=org_id, user_id=user.id, role="member")

    async def _fake_accept(_session: Any, _invite: OrganizationInvite, _user: User) -> OrganizationMember:
        assert _invite is invite
        assert _user is user
        return accepted

    monkeypatch.setattr(organizations, "get_active_membership", _fake_get_active)
    monkeypatch.setattr(organizations, "_find_pending_invite", _fake_find)
    monkeypatch.setattr(organizations, "accept_invite", _fake_accept)

    session = _FakeSession(exec_results=[])
    out = await organizations.ensure_member_for_user(session, user)
    assert out is accepted


@pytest.mark.asyncio
async def test_ensure_member_for_user_creates_default_org_and_first_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(clerk_user_id="u1", email=None)
    org = Organization(id=uuid4(), name=organizations.DEFAULT_ORG_NAME)

    async def _fake_get_active(_session: Any, _user: User) -> None:
        return None

    async def _fake_ensure_default(_session: Any) -> Organization:
        return org

    monkeypatch.setattr(organizations, "get_active_membership", _fake_get_active)
    monkeypatch.setattr(organizations, "ensure_default_org", _fake_ensure_default)

    # member_count query returns 0 -> first member becomes owner
    session = _FakeSession(exec_results=[_FakeExecResult(one_value=0)])

    out = await organizations.ensure_member_for_user(session, user)
    assert out.organization_id == org.id
    assert out.user_id == user.id
    assert out.role == "owner"
    assert out.all_boards_read is True
    assert out.all_boards_write is True
    assert user.active_organization_id == org.id
    assert session.committed == 1


@pytest.mark.asyncio
async def test_has_board_access_denies_cross_org() -> None:
    session = _FakeSession(exec_results=[])
    member = OrganizationMember(organization_id=uuid4(), user_id=uuid4(), role="member")
    board = Board(id=uuid4(), organization_id=uuid4(), name="b", slug="b")
    assert await organizations.has_board_access(session, member=member, board=board, write=False) is False


@pytest.mark.asyncio
async def test_has_board_access_uses_org_board_access_row_read_and_write() -> None:
    org_id = uuid4()
    member = OrganizationMember(id=uuid4(), organization_id=org_id, user_id=uuid4(), role="member")
    board = Board(id=uuid4(), organization_id=org_id, name="b", slug="b")

    access = OrganizationBoardAccess(
        organization_member_id=member.id,
        board_id=board.id,
        can_read=True,
        can_write=False,
    )
    session = _FakeSession(exec_results=[_FakeExecResult(first_value=access)])
    assert await organizations.has_board_access(session, member=member, board=board, write=False) is True

    access2 = OrganizationBoardAccess(
        organization_member_id=member.id,
        board_id=board.id,
        can_read=False,
        can_write=True,
    )
    session2 = _FakeSession(exec_results=[_FakeExecResult(first_value=access2)])
    assert await organizations.has_board_access(session2, member=member, board=board, write=False) is True

    access3 = OrganizationBoardAccess(
        organization_member_id=member.id,
        board_id=board.id,
        can_read=True,
        can_write=False,
    )
    session3 = _FakeSession(exec_results=[_FakeExecResult(first_value=access3)])
    assert await organizations.has_board_access(session3, member=member, board=board, write=True) is False


@pytest.mark.asyncio
async def test_require_board_access_raises_when_no_member(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(clerk_user_id="u1")
    board = Board(id=uuid4(), organization_id=uuid4(), name="b", slug="b")

    async def _fake_get_member(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(organizations, "get_member", _fake_get_member)

    session = _FakeSession(exec_results=[])
    with pytest.raises(HTTPException) as exc:
        await organizations.require_board_access(session, user=user, board=board, write=False)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_apply_member_access_update_deletes_existing_and_adds_rows_when_not_all_boards() -> None:
    member = OrganizationMember(id=uuid4(), organization_id=uuid4(), user_id=uuid4(), role="member")
    update = OrganizationMemberAccessUpdate(
        all_boards_read=False,
        all_boards_write=False,
        board_access=[
            OrganizationBoardAccessSpec(board_id=uuid4(), can_read=True, can_write=False),
            OrganizationBoardAccessSpec(board_id=uuid4(), can_read=True, can_write=True),
        ],
    )
    session = _FakeSession(exec_results=[])

    await organizations.apply_member_access_update(session, member=member, update=update)

    # delete statement executed once
    assert len(session.executed) == 1
    # member + new rows added
    assert member in session.added
    assert len(session.added_all) == 1
    assert len(session.added_all[0]) == 2


@pytest.mark.asyncio
async def test_apply_invite_to_member_upgrades_role_and_merges_access_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = uuid4()
    member = OrganizationMember(
        id=uuid4(),
        organization_id=org_id,
        user_id=uuid4(),
        role="member",
        all_boards_read=False,
        all_boards_write=False,
    )

    invite = OrganizationInvite(
        id=uuid4(),
        organization_id=org_id,
        invited_email="x@example.com",
        token="t",
        role="admin",  # upgrade
        all_boards_read=False,
        all_boards_write=False,
    )

    board_id = uuid4()
    invite_access = OrganizationInviteBoardAccess(
        organization_invite_id=invite.id,
        board_id=board_id,
        can_read=True,
        can_write=True,
    )

    # 1st exec: invite access rows list
    # 2nd exec: existing access (none)
    session = _FakeSession(exec_results=[
        [invite_access],
        _FakeExecResult(first_value=None),
    ])

    await organizations.apply_invite_to_member(session, member=member, invite=invite)

    assert member.role == "admin"
    # should have added a new OrganizationBoardAccess row
    assert any(isinstance(x, OrganizationBoardAccess) for x in session.added)
