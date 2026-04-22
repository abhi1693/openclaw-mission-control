# ruff: noqa: INP001
"""Unit tests for Phase VI §I6 blocked-lane comment suppression."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.lane_quieting import should_suppress_comment_for_blocked_lane


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task, Blocker]]:
    org = Organization(id=uuid4(), name="org")
    sqlite_session.add(org)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        name="board",
        slug="board",
        description="x",
        rollout_flags={"structured_blockers_v1": True},
    )
    sqlite_session.add(board)
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="t",
        status="in_progress",
        assigned_agent_id=uuid4(),
    )
    sqlite_session.add(task)
    blocker = Blocker(
        id=uuid4(),
        board_id=board.id,
        task_id=task.id,
        category="source",
        owner_role="frontend-dev",
        acknowledged_at=datetime.now(timezone.utc),
    )
    sqlite_session.add(blocker)
    await sqlite_session.commit()
    yield sqlite_session, board, task, blocker


@pytest.mark.asyncio
async def test_non_owner_agent_suppressed_when_board_graduated(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    session, _board, task, _blocker = seeded
    assert await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),  # not task.assigned_agent_id
    )


@pytest.mark.asyncio
async def test_owner_agent_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """The task owner is explicitly exempt — they must still be able
    to post progress while the rest of the lane is quiet."""

    session, _board, task, _blocker = seeded
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=task.assigned_agent_id,
    )


@pytest.mark.asyncio
async def test_user_operator_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """User-token callers (human operators) are represented by
    ``author_agent_id=None`` — always allowed."""

    session, _board, task, _blocker = seeded
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=None,
    )


@pytest.mark.asyncio
async def test_rollout_flag_off_keeps_legacy_behaviour(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Boards without ``structured_blockers_v1`` don't opt into lane
    quieting — every agent can still comment."""

    session, board, task, _blocker = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_unacknowledged_blocker_does_not_suppress(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Unacknowledged blockers still need traffic so the owner can
    pick them up — suppression only kicks in after ack."""

    session, _board, task, blocker = seeded
    blocker.acknowledged_at = None
    session.add(blocker)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_resolved_blocker_does_not_suppress(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Once a blocker is resolved the lane re-opens."""

    session, _board, task, blocker = seeded
    blocker.resolved_at = datetime.now(timezone.utc)
    session.add(blocker)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_task_without_blockers_is_open(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """A task with no blocker rows at all is open to every commenter."""

    session, board, _task, _blocker = seeded
    bare_task = Task(
        id=uuid4(),
        board_id=board.id,
        title="bare",
        status="in_progress",
    )
    session.add(bare_task)
    await session.commit()
    assert not await should_suppress_comment_for_blocked_lane(
        session,
        task=bare_task,
        author_agent_id=uuid4(),
    )


# --------------------------------------------------------------------
# H1 regression from Codex review: PATCH with both a task mutation
# AND a blocked-lane comment must be atomic — reject the whole PATCH
# at the gate instead of committing the mutation then 403'ing the
# comment.
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_lane_gate_runs_before_task_mutation_commits(
    seeded: tuple[AsyncSession, Board, Task, Blocker],
) -> None:
    """Compose a ``_TaskUpdateInput`` that carries both a real mutation
    and a comment, then run ``_finalize_updated_task`` — the gate
    should raise 403 BEFORE the task mutation lands, so a re-read of
    the task shows the original status.

    This locks the Codex-flagged partial-commit bug: prior to the fix,
    the task mutation committed at line 3558 and the gate raised
    afterwards in ``_record_task_comment_from_update``.
    """

    from dataclasses import dataclass

    from fastapi import HTTPException

    from app.api import tasks as tasks_module

    session, board, task, _blocker = seeded

    # Build a minimal ``ActorContext`` + ``_TaskUpdateInput`` shape.
    @dataclass
    class _ActorStub:
        agent: object
        actor_type: str = "agent"
        user: object | None = None

    @dataclass
    class _AgentStub:
        id: object

    # Non-owner agent (the lane quieting is directed at them).
    other_agent_id = uuid4()
    actor = _ActorStub(agent=_AgentStub(id=other_agent_id))

    original_status = task.status
    update = tasks_module._TaskUpdateInput(
        task=task,
        actor=actor,  # type: ignore[arg-type]
        board_id=board.id,
        previous_status=original_status,
        previous_assigned=task.assigned_agent_id,
        status_requested=True,
        updates={"status": "review"},
        comment="trying to slip a comment in",
        depends_on_task_ids=None,
        tag_ids=None,
        custom_field_values={},
        custom_field_values_set=False,
    )

    with pytest.raises(HTTPException) as exc:
        await tasks_module._finalize_updated_task(session, update=update)
    assert exc.value.status_code == 403
    # Re-read the task — status should be unchanged.
    await session.rollback()
    await session.refresh(task)
    assert task.status == original_status
