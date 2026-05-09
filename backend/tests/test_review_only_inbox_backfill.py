# ruff: noqa: INP001
"""Backfill must use the admin update path (same pattern as
scripts/normalize_board_delivery_contract.py:157-174) so it produces
the normal status-change activity event, runs lead-assignment
normalization, and is idempotent. A naive `task.status = 'review';
commit()` skips all of that."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.activity_events import ActivityEvent
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.models.users import User


@pytest.mark.asyncio
async def test_backfill_advances_review_only_inbox_to_review(
    sqlite_session: AsyncSession,
) -> None:
    from scripts.backfill_review_only_inbox import backfill_async
    session = sqlite_session
    org = Organization(id=uuid4(), name="o")
    board = Board(id=uuid4(), organization_id=org.id, name="b", slug="b1")
    user = User(id=uuid4(), clerk_user_id="cu", email="op@example.com")
    session.add_all([org, board, user])

    stuck = Task(
        id=uuid4(), board_id=board.id, title="stuck",
        status="inbox", review_packet_type="review_only",
    )
    legit = Task(
        id=uuid4(), board_id=board.id, title="real",
        status="inbox", review_packet_type="frontend_ui",
    )
    done = Task(
        id=uuid4(), board_id=board.id, title="finished",
        status="done", review_packet_type="review_only",
    )
    session.add_all([stuck, legit, done])
    await session.commit()

    advanced = await backfill_async(session, actor_user=user, dry_run=False)
    assert advanced == [stuck.id]
    await session.refresh(stuck)
    await session.refresh(legit)
    await session.refresh(done)
    assert stuck.status == "review"
    assert legit.status == "inbox"
    assert done.status == "done"


@pytest.mark.asyncio
async def test_backfill_records_status_change_activity(
    sqlite_session: AsyncSession,
) -> None:
    """Without going through _finalize_updated_task the script would
    silently flip status. The activity row is what the UI shows in the
    task history."""
    from scripts.backfill_review_only_inbox import backfill_async
    session = sqlite_session
    org = Organization(id=uuid4(), name="o")
    board = Board(id=uuid4(), organization_id=org.id, name="b", slug="b2")
    user = User(id=uuid4(), clerk_user_id="cu", email="op@example.com")
    stuck = Task(
        id=uuid4(), board_id=board.id, title="stuck",
        status="inbox", review_packet_type="review_only",
    )
    session.add_all([org, board, user, stuck])
    await session.commit()

    await backfill_async(session, actor_user=user, dry_run=False)

    events = (await session.exec(
        select(ActivityEvent).where(ActivityEvent.task_id == stuck.id)
    )).all()
    types = {e.event_type for e in events}
    assert "task.status_changed" in types, (
        f"expected status_changed activity event; got {types!r}"
    )


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_mutate(
    sqlite_session: AsyncSession,
) -> None:
    from scripts.backfill_review_only_inbox import backfill_async
    session = sqlite_session
    org = Organization(id=uuid4(), name="o")
    board = Board(id=uuid4(), organization_id=org.id, name="b", slug="b3")
    user = User(id=uuid4(), clerk_user_id="cu", email="op@example.com")
    stuck = Task(
        id=uuid4(), board_id=board.id, title="stuck",
        status="inbox", review_packet_type="review_only",
    )
    session.add_all([org, board, user, stuck])
    await session.commit()

    advanced = await backfill_async(session, actor_user=user, dry_run=True)
    assert advanced == [stuck.id]  # reported but not committed
    await session.refresh(stuck)
    assert stuck.status == "inbox"


@pytest.mark.asyncio
async def test_backfill_idempotent(
    sqlite_session: AsyncSession,
) -> None:
    from scripts.backfill_review_only_inbox import backfill_async
    session = sqlite_session
    org = Organization(id=uuid4(), name="o")
    board = Board(id=uuid4(), organization_id=org.id, name="b", slug="b4")
    user = User(id=uuid4(), clerk_user_id="cu", email="op@example.com")
    stuck = Task(
        id=uuid4(), board_id=board.id, title="stuck",
        status="inbox", review_packet_type="review_only",
    )
    session.add_all([org, board, user, stuck])
    await session.commit()

    first = await backfill_async(session, actor_user=user, dry_run=False)
    second = await backfill_async(session, actor_user=user, dry_run=False)
    assert first == [stuck.id]
    assert second == []  # second run is no-op


@pytest.mark.asyncio
async def test_backfill_scoped_to_board_id(
    sqlite_session: AsyncSession,
) -> None:
    """When --board-id is provided, backfill must touch ONLY that board."""
    from scripts.backfill_review_only_inbox import backfill_async
    session = sqlite_session
    org = Organization(id=uuid4(), name="o")
    board_a = Board(id=uuid4(), organization_id=org.id, name="A", slug="ba")
    board_b = Board(id=uuid4(), organization_id=org.id, name="B", slug="bb")
    user = User(id=uuid4(), clerk_user_id="cu", email="op@example.com")
    stuck_a = Task(
        id=uuid4(), board_id=board_a.id, title="A",
        status="inbox", review_packet_type="review_only",
    )
    stuck_b = Task(
        id=uuid4(), board_id=board_b.id, title="B",
        status="inbox", review_packet_type="review_only",
    )
    session.add_all([org, board_a, board_b, user, stuck_a, stuck_b])
    await session.commit()

    advanced = await backfill_async(
        session, actor_user=user, dry_run=False, board_id=board_a.id,
    )
    assert advanced == [stuck_a.id]
    await session.refresh(stuck_b)
    assert stuck_b.status == "inbox"  # other board untouched
