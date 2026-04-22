# ruff: noqa: INP001
"""Part D.1 tests — auto-file runtime Blocker on subagent-failure payload."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blockers import Blocker
from app.models.boards import Board
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
    """Older 4.20 builds may omit ``parent_turn_id`` — it's metadata,
    not load-bearing. Parser must still accept the payload."""

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
    """4.19 and earlier emit subagent-failure events without
    ``requested_role``. Parser must return None so the hook degrades
    to a no-op WARN log rather than filing a half-populated row."""

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
    parent_agent_id = uuid4()
    blocker_id = await file_subagent_failure_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        parent_agent_id=parent_agent_id,
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
    assert blocker.created_by_agent_id == parent_agent_id
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


@pytest.mark.asyncio
async def test_dedupes_on_same_task_role(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Retry storms for the same child-agent class must not multiply
    rows. Wording drift (different runtime_ms, different error_class)
    still dedupes — the key is (task, requested_role), not the
    citation string."""

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
    """A second failure for a DIFFERENT child-agent class on the same
    task is its own routing problem — file a new row, don't collapse
    two distinct owner lanes into one."""

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
    """Once the operator resolves the previous runtime blocker, a
    recurrence of the same child-agent failure files fresh — the
    resolved row is audit, the new row is the current state."""

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
