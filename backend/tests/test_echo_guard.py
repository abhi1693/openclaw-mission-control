# ruff: noqa: INP001
"""Phase VII tests — comment-echo write gate.

Regression coverage for the 2026-04-17 22:30 UTC Architect↔Supervisor
echo storm. The storm samples are the ground-truth corpus: the gate
MUST suppress them, and it MUST NOT suppress messages carrying real
evidence or a state-delta.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.comment_classifier import ClassifierFlag
from app.services.echo_guard import classify_for_echo

_ARCH_SAMPLE = (
    "@Supervisor @QA-E2E @Programmer-Frontend @lead Acknowledged. "
    "I am holding D.1 on that exact truth. No QA-forward path and no "
    "clear path from me until the on-file Admin inconsistency is "
    "corrected, Backup & Restore is no longer orphaned from the page "
    "body, and the next handoff can honestly name the live validation "
    "target."
)
_SUPE_SAMPLE = (
    "Confirmed. Lead is holding the same D.1 truth: keep the lane "
    "fail-closed until the on-file Admin inconsistency is corrected "
    "and the next QA-forward handoff honestly names the live "
    "validation target and build."
)


@pytest_asyncio.fixture
async def seeded(
    sqlite_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, Board, Task, "UUID"]]:
    from uuid import UUID as _UUID  # local alias — test scope only

    org = Organization(id=uuid4(), name="org")
    sqlite_session.add(org)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        name="b",
        slug="b",
        description="x",
        rollout_flags={"comment_echo_guard_v1": True},
    )
    sqlite_session.add(board)
    # Strict packet type — the classifier's LAX_PACKET_TYPES carve-out
    # exempts ``review_only``/``content_copy``/``other`` from long-form
    # ack-only/echo-shape flagging (those legitimately carry short
    # alignment comments). The storm happened on a frontend-implementation
    # task, i.e. strict packet type.
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="D.1",
        status="in_progress",
        review_packet_type="frontend_ui",
    )
    sqlite_session.add(task)
    await sqlite_session.commit()
    agent_id: _UUID = uuid4()
    yield sqlite_session, board, task, agent_id


async def _seed_prior_comment(
    session: AsyncSession,
    *,
    task: Task,
    agent_id: "UUID",
    message: str,
    seconds_ago: float = 30.0,
) -> ActivityEvent:
    event = ActivityEvent(
        event_type="task.comment",
        message=message,
        task_id=task.id,
        board_id=task.board_id,
        agent_id=agent_id,
        created_at=utcnow() - timedelta(seconds=seconds_ago),
    )
    session.add(event)
    await session.commit()
    return event


# --------------------------------------------------------------------
# Core suppression cases — the 2026-04-17 storm must be caught.
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_architect_storm_sample_is_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """Architect's leading-@mention 'Acknowledged. holding on that exact truth…'
    was the half the current ack_only classifier missed. Gate must catch it."""

    session, _board, task, agent_id = seeded
    await _seed_prior_comment(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    assert result.should_suppress is True
    assert ClassifierFlag.ECHO_SHAPE in result.classifier_flags


@pytest.mark.asyncio
async def test_supervisor_storm_sample_is_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    session, _board, task, agent_id = seeded
    await _seed_prior_comment(session, task=task, agent_id=agent_id, message=_SUPE_SAMPLE)
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_SUPE_SAMPLE)
    assert result.should_suppress is True


# --------------------------------------------------------------------
# Exemption branches — must NOT suppress.
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_same_task_comment_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """No prior within the window → not an echo by definition."""

    session, _board, task, agent_id = seeded
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    assert result.should_suppress is False


@pytest.mark.asyncio
async def test_user_operator_never_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """``agent_id=None`` is the user-token caller — always exempt."""

    session, _board, task, _agent = seeded
    result = await classify_for_echo(session, task=task, agent_id=None, message=_ARCH_SAMPLE)
    assert result.should_suppress is False


@pytest.mark.asyncio
async def test_message_with_evidence_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """A message carrying a SHA/URL/file-reference doesn't fire
    ECHO_SHAPE even if the ack-phrase regex matches. Locks the
    negative-evidence gate."""

    session, _board, task, agent_id = seeded
    await _seed_prior_comment(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    legit = (
        "Acknowledged. Retested at commit abc123f. Lighthouse CLS=0.08 "
        "PASS. Screenshot: http://192.168.2.60:3000/runs/abc123f.png"
    )
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=legit)
    assert result.should_suppress is False


@pytest.mark.asyncio
async def test_prior_outside_window_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """Prior comment older than ECHO_GUARD_WINDOW_SECONDS (30 min) is
    stale — two independent decisions to comment, not an echo."""

    session, _board, task, agent_id = seeded
    await _seed_prior_comment(
        session,
        task=task,
        agent_id=agent_id,
        message=_ARCH_SAMPLE,
        seconds_ago=60 * 60,  # 1h ago — well outside window
    )
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    assert result.should_suppress is False


@pytest.mark.asyncio
async def test_blocker_filed_since_prior_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """State delta = new blocker on this task since the prior comment.
    Legitimate alignment after a real event — must not suppress."""

    session, _board, task, agent_id = seeded
    prior = await _seed_prior_comment(
        session,
        task=task,
        agent_id=agent_id,
        message=_ARCH_SAMPLE,
        seconds_ago=120.0,
    )
    # Blocker filed AFTER the prior comment, BEFORE this one.
    session.add(
        Blocker(
            id=uuid4(),
            board_id=task.board_id,
            task_id=task.id,
            category="source",
            owner_role="frontend-dev",
            created_at=prior.created_at + timedelta(seconds=30),
        )
    )
    await session.commit()
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    assert result.should_suppress is False


@pytest.mark.asyncio
async def test_flag_off_observes_but_does_not_suppress(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """``comment_echo_guard_v1`` off = shadow mode. Classifier still
    fires (operator uses that to tune rollout), but write is allowed."""

    session, board, task, agent_id = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    await _seed_prior_comment(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=_ARCH_SAMPLE)
    assert result.should_suppress is False
    assert result.reason == "observe"
    assert ClassifierFlag.ECHO_SHAPE in result.classifier_flags


@pytest.mark.asyncio
async def test_non_echo_shape_message_not_suppressed(
    seeded: tuple[AsyncSession, Board, Task, "UUID"],
) -> None:
    """A genuine progress update after a prior same-author comment
    must pass — the gate keys on shape, not on cadence alone."""

    session, _board, task, agent_id = seeded
    await _seed_prior_comment(
        session,
        task=task,
        agent_id=agent_id,
        message="Moving to in_progress. Starting on the Admin form fix.",
    )
    progress = (
        "PR abc1234 posted. Admin form now renders the Backup & Restore "
        "section. Running Playwright on http://192.168.2.60:3000/admin "
        "next."
    )
    result = await classify_for_echo(session, task=task, agent_id=agent_id, message=progress)
    assert result.should_suppress is False
