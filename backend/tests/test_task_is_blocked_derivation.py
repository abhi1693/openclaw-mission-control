# ruff: noqa: INP001
"""Unit test for the Phase II is_blocked derivation (plan §I1).

``_task_is_blocked`` gained a third OR: an open ``Blocker`` row counts
as blocked even when the dependency graph is clean. The helper + its
batch preloader are decoupled from the handler, so this covers the
derivation contract without spinning up the whole task stack.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.tasks import _task_is_blocked
from app.models.blockers import Blocker
from app.models.operator_decisions import (
    OperatorDecision,
    OperatorDecisionTaskLink,
)
from app.models.tasks import Task
from app.services.blockers import task_has_open_blocker, task_ids_with_open_blocker
from app.services.operator_decisions import (
    task_has_pending_operator_decision,
    task_ids_with_pending_operator_decision,
)


def _task(**overrides: object) -> Task:
    defaults: dict[str, object] = {
        "board_id": uuid4(),
        "title": "Example",
        "status": "in_progress",
    }
    defaults.update(overrides)
    return Task(**defaults)  # type: ignore[arg-type]


def test_open_blocker_flag_flips_is_blocked_true() -> None:
    """An open blocker counts even when the dependency graph is empty."""

    task = _task()
    assert not _task_is_blocked(task, [])
    assert _task_is_blocked(task, [], has_open_blocker=True)


def test_pending_operator_decision_flips_is_blocked_true() -> None:
    """The Phase III bridge: a pending OperatorDecision blocks the task
    even when the legacy flag is False and no Blocker row exists."""

    task = _task()
    assert not _task_is_blocked(task, [])
    assert _task_is_blocked(task, [], has_pending_operator_decision=True)


def test_legacy_operator_decision_flag_still_blocks() -> None:
    """Compatibility rule: the legacy bool flag keeps working during
    migration, regardless of whether the entity table has any rows."""

    task = _task(operator_decision_required=True)
    assert _task_is_blocked(task, [])


def test_terminal_status_still_clears_open_blocker() -> None:
    """Done/cancelled tasks are not blocked regardless of blockers."""

    for status in ("done", "cancelled"):
        task = _task(status=status)
        assert not _task_is_blocked(task, [], has_open_blocker=True)


@pytest.mark.asyncio
async def test_scalar_exists_returns_false_on_empty_table(
    sqlite_session: AsyncSession,
) -> None:
    """task_has_open_blocker on a task with no rows must be False —
    guards against a ``Row``-truthiness false positive."""

    assert not await task_has_open_blocker(sqlite_session, board_id=uuid4(), task_id=uuid4())


@pytest.mark.asyncio
async def test_scalar_exists_honors_resolved_at(
    sqlite_session: AsyncSession,
) -> None:
    """Resolved blockers must not satisfy the EXISTS clause."""

    board_id = uuid4()
    open_task_id = uuid4()
    resolved_task_id = uuid4()
    sqlite_session.add(
        Blocker(
            board_id=board_id,
            task_id=open_task_id,
            category="source",
            owner_role="dev",
        ),
    )
    resolved = Blocker(
        board_id=board_id,
        task_id=resolved_task_id,
        category="source",
        owner_role="dev",
    )
    sqlite_session.add(resolved)
    await sqlite_session.commit()
    resolved.resolved_at = resolved.created_at
    sqlite_session.add(resolved)
    await sqlite_session.commit()

    assert await task_has_open_blocker(sqlite_session, board_id=board_id, task_id=open_task_id)
    assert not await task_has_open_blocker(
        sqlite_session, board_id=board_id, task_id=resolved_task_id
    )


@pytest.mark.asyncio
async def test_pending_decision_preloader_joins_link_and_filters_pending(
    sqlite_session: AsyncSession,
) -> None:
    """Batch preloader must return only tasks with a PENDING (not
    resolved, not cancelled) decision linked via the sidecar table."""

    board_id = uuid4()
    pending_task_id = uuid4()
    resolved_task_id = uuid4()
    unlinked_task_id = uuid4()
    pending = OperatorDecision(board_id=board_id, question="pending?")
    resolved = OperatorDecision(board_id=board_id, question="resolved?", status="resolved")
    sqlite_session.add(pending)
    sqlite_session.add(resolved)
    await sqlite_session.commit()
    sqlite_session.add(
        OperatorDecisionTaskLink(decision_id=pending.id, task_id=pending_task_id),
    )
    sqlite_session.add(
        OperatorDecisionTaskLink(decision_id=resolved.id, task_id=resolved_task_id),
    )
    await sqlite_session.commit()

    blocked = await task_ids_with_pending_operator_decision(
        sqlite_session,
        board_id=board_id,
        task_ids=[pending_task_id, resolved_task_id, unlinked_task_id],
    )
    assert blocked == {pending_task_id}

    assert await task_has_pending_operator_decision(
        sqlite_session, board_id=board_id, task_id=pending_task_id
    )
    assert not await task_has_pending_operator_decision(
        sqlite_session, board_id=board_id, task_id=resolved_task_id
    )


@pytest.mark.asyncio
async def test_batch_preloader_returns_only_open_blocker_task_ids(
    sqlite_session: AsyncSession,
) -> None:
    """``task_ids_with_open_blocker`` must exclude resolved rows."""

    board_id = uuid4()
    open_task_id = uuid4()
    resolved_task_id = uuid4()
    no_blocker_task_id = uuid4()
    sqlite_session.add(
        Blocker(
            board_id=board_id,
            task_id=open_task_id,
            category="source",
            owner_role="frontend-dev",
        ),
    )
    resolved = Blocker(
        board_id=board_id,
        task_id=resolved_task_id,
        category="source",
        owner_role="frontend-dev",
    )
    sqlite_session.add(resolved)
    await sqlite_session.commit()
    resolved.resolved_at = resolved.created_at
    sqlite_session.add(resolved)
    await sqlite_session.commit()

    blocked = await task_ids_with_open_blocker(
        sqlite_session,
        board_id=board_id,
        task_ids=[open_task_id, resolved_task_id, no_blocker_task_id],
    )
    assert blocked == {open_task_id}
