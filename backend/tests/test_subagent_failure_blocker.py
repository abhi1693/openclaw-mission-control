# ruff: noqa: INP001
"""Part D.1 tests — auto-file runtime Blocker on subagent-failure payload."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.subagent_failure_blocker import (
    SubagentFailurePayload,
    file_subagent_failure_blocker_if_configured,
    parse_subagent_failure_payload,
)


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task]]:
    org = Organization(id=uuid4(), name="org")
    sqlite_session.add(org)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        name="b",
        slug="b",
        description="x",
        rollout_flags={"structured_blockers_v1": True},
    )
    sqlite_session.add(board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="in_progress",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    yield sqlite_session, board, task


# --------------------------------------------------------------------
# parse_subagent_failure_payload
# --------------------------------------------------------------------


def test_parser_accepts_full_payload() -> None:
    payload = parse_subagent_failure_payload(
        {
            "requested_role": "codex",
            "runtime_ms": 4123,
            "error_class": "TimeoutError",
            "parent_turn_id": "turn-42",
        }
    )
    assert payload == SubagentFailurePayload(
        requested_role="codex",
        runtime_ms=4123,
        error_class="TimeoutError",
        parent_turn_id="turn-42",
    )


def test_parser_accepts_missing_parent_turn_id() -> None:
    payload = parse_subagent_failure_payload(
        {
            "requested_role": "codex",
            "runtime_ms": 10,
            "error_class": "BadGateway",
        }
    )
    assert payload is not None
    assert payload.parent_turn_id is None


def test_parser_trims_whitespace() -> None:
    payload = parse_subagent_failure_payload(
        {
            "requested_role": "  codex  ",
            "runtime_ms": 1,
            "error_class": "  Boom  ",
        }
    )
    assert payload is not None
    assert payload.requested_role == "codex"
    assert payload.error_class == "Boom"


def test_parser_returns_none_for_older_gateway_missing_role() -> None:
    assert (
        parse_subagent_failure_payload(
            {"runtime_ms": 100, "error_class": "Boom"}
        )
        is None
    )


def test_parser_returns_none_for_missing_runtime_ms() -> None:
    assert (
        parse_subagent_failure_payload(
            {"requested_role": "codex", "error_class": "Boom"}
        )
        is None
    )


def test_parser_returns_none_for_negative_runtime_ms() -> None:
    assert (
        parse_subagent_failure_payload(
            {
                "requested_role": "codex",
                "runtime_ms": -1,
                "error_class": "Boom",
            }
        )
        is None
    )


def test_parser_returns_none_for_bool_runtime_ms() -> None:
    """``bool`` is an ``int`` subclass — a gateway payload that encodes
    True/False for runtime_ms is wrong and must not silently become
    runtime_ms=1."""

    assert (
        parse_subagent_failure_payload(
            {
                "requested_role": "codex",
                "runtime_ms": True,
                "error_class": "Boom",
            }
        )
        is None
    )


def test_parser_returns_none_for_runtime_ms_over_cap() -> None:
    """Guards ``str(runtime_ms)`` against CPython's 4300-digit int→str
    limit and anchors the citation string's max length."""

    huge = 7 * 24 * 60 * 60 * 1000 + 1  # 1ms past the one-week cap
    assert (
        parse_subagent_failure_payload(
            {
                "requested_role": "codex",
                "runtime_ms": huge,
                "error_class": "Boom",
            }
        )
        is None
    )


def test_parser_returns_none_for_overlong_role() -> None:
    """``Blocker.owner_role`` is VARCHAR(64) in Postgres — reject at
    payload parse time rather than commit time."""

    assert (
        parse_subagent_failure_payload(
            {
                "requested_role": "x" * 65,
                "runtime_ms": 10,
                "error_class": "Boom",
            }
        )
        is None
    )


def test_parser_warn_path_tolerates_mixed_type_keys() -> None:
    """A malformed dict with mixed-type keys (e.g. ``{2: "b", "a": 1}``)
    must degrade cleanly — the WARN path must not itself raise
    ``TypeError`` from ``sorted()`` on uncomparable keys."""

    assert (
        parse_subagent_failure_payload(
            {2: "not-a-role", "runtime_ms": 10, "error_class": "Boom"}
        )
        is None
    )


def test_parser_returns_none_for_missing_error_class() -> None:
    assert (
        parse_subagent_failure_payload(
            {"requested_role": "codex", "runtime_ms": 1}
        )
        is None
    )


def test_parser_returns_none_for_non_dict() -> None:
    assert parse_subagent_failure_payload(None) is None
    assert parse_subagent_failure_payload("not a dict") is None
    assert parse_subagent_failure_payload(42) is None


# --------------------------------------------------------------------
# file_subagent_failure_blocker_if_configured
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_files_runtime_blocker_when_flag_enabled(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    session, board, task = seeded
    # Seed a real parent Agent so ``created_by_agent_id`` exercises the
    # actual FK path rather than relying on SQLite's default FK-off
    # behaviour to paper over a missing row.
    gateway = Gateway(
        id=uuid4(),
        organization_id=board.organization_id,
        name="gw",
        url="https://gw.local",
        workspace_root="/tmp/w",
    )
    session.add(gateway)
    parent_agent = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="parent",
        status="online",
    )
    session.add(parent_agent)
    await session.commit()

    blocker_id = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent_agent.id,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=5123,
            error_class="TimeoutError",
        ),
    )
    assert blocker_id is not None
    blocker = (
        await session.exec(
            select(Blocker).where(col(Blocker.id) == blocker_id)
        )
    ).first()
    assert blocker is not None
    assert blocker.category == "runtime"
    assert blocker.owner_role == "codex"
    assert blocker.required_artifact is None
    assert blocker.created_by_agent_id == parent_agent.id
    assert blocker.citation == "subagent codex failed after 5123ms: TimeoutError"


@pytest.mark.asyncio
async def test_skips_when_board_flag_off(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    session, board, task = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    blocker_id = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=uuid4(),
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=100,
            error_class="Boom",
        ),
    )
    assert blocker_id is None
    # Lock "gate-off leaks no state" — returning None isn't enough, the
    # table must also be empty.
    rows = (
        await session.exec(
            select(Blocker).where(col(Blocker.task_id) == task.id)
        )
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_dedupes_on_same_task_role(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Retry with different runtime_ms/error_class still dedupes —
    the key is (task, requested_role), not the citation string."""

    session, board, task = seeded
    parent = uuid4()
    first = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=5000,
            error_class="TimeoutError",
        ),
    )
    second = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=7000,
            error_class="BadGateway",
        ),
    )
    assert first is not None
    assert second is None
    rows = (
        await session.exec(
            select(Blocker).where(col(Blocker.task_id) == task.id)
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_different_role_files_separate_blocker(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Distinct child-agent classes get distinct rows — separate
    routing lanes."""

    session, board, task = seeded
    parent = uuid4()
    a = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=100,
            error_class="Boom",
        ),
    )
    b = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="claude-haiku",
            runtime_ms=200,
            error_class="Boom",
        ),
    )
    assert a is not None
    assert b is not None
    assert a != b


@pytest.mark.asyncio
async def test_resolved_blocker_does_not_block_new_file(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Resolved row is audit; a recurrence files a fresh current-state row."""

    from app.core.time import utcnow

    session, board, task = seeded
    parent = uuid4()
    first = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=100,
            error_class="Boom",
        ),
    )
    assert first is not None
    blocker = await session.get(Blocker, first)
    assert blocker is not None
    blocker.resolved_at = utcnow()
    session.add(blocker)
    await session.commit()

    second = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=200,
            error_class="Boom",
        ),
    )
    assert second is not None
    assert second != first


@pytest.mark.asyncio
async def test_integrity_error_from_partial_unique_index_returns_none(
    seeded: tuple[AsyncSession, Board, Task],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the check-then-insert race: monkey-patch the EXISTS
    pre-check to always return False so both the first and the
    would-be-racing second filer call reach the INSERT. The second
    INSERT must hit ``uq_blockers_runtime_owner_open`` and come back
    as None — not crash, not double-insert."""

    from app.services import subagent_failure_blocker as module

    session, board, task = seeded
    payload = SubagentFailurePayload(
        requested_role="codex",
        runtime_ms=1,
        error_class="E",
    )

    # Verify the open-row count BEFORE triggering the race so the
    # post-race session (which aiosqlite leaves in a fragile state
    # after an IntegrityError + rollback) doesn't need to be queried
    # for the assertion.
    first = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=None,
        payload=payload,
    )
    assert first is not None
    baseline = (
        await session.exec(
            select(Blocker).where(col(Blocker.task_id) == task.id)
        )
    ).all()
    assert len(baseline) == 1

    async def _always_false(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(
        module, "_open_subagent_runtime_blocker_exists", _always_false
    )

    second = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=None,
        payload=payload,
    )
    assert second is None


@pytest.mark.asyncio
async def test_citation_is_truncated_at_max_length(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Operator dashboards expect one bounded citation shape across
    feeders — parity with D.2's 512-char cap."""

    session, board, task = seeded
    blocker_id = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=None,
        payload=SubagentFailurePayload(
            requested_role="codex",
            runtime_ms=1,
            error_class="E" * 1000,
        ),
    )
    assert blocker_id is not None
    blocker = await session.get(Blocker, blocker_id)
    assert blocker is not None
    assert blocker.citation is not None
    assert len(blocker.citation) <= 512
    assert blocker.citation.endswith("…")
