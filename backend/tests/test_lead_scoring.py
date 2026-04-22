# ruff: noqa: INP001
"""Unit tests for Phase VI §I5 lead heartbeat no-op scoring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.shadow_metric_events import ShadowMetricEvent
from app.services.lead_scoring import (
    count_lead_actions_since,
    last_scoring_bookmark,
    score_all_leads_once,
    score_lead_once,
)
from app.services.shadow_metrics import (
    EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE,
    EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT,
)


@pytest_asyncio.fixture
async def seeded(
    sqlite_engine: AsyncEngine,
    sqlite_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncSession, Board, Agent]]:
    # Redirect the emit helpers' dedicated-session factory at the
    # test engine so ``score_lead_once`` writes land in the same DB
    # the assertions read from.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import shadow_metrics as shadow_metrics_module

    test_session_maker = async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(
        shadow_metrics_module, "async_session_maker", test_session_maker
    )

    org = Organization(id=uuid4(), name="org")
    sqlite_session.add(org)
    gateway = Gateway(
        id=uuid4(),
        organization_id=org.id,
        name="gw",
        url="https://gw.local",
        workspace_root="/tmp/w",
    )
    sqlite_session.add(gateway)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        gateway_id=gateway.id,
        name="board",
        slug="board",
        description="x",
        rollout_flags={"lead_scoring_v1": True},
    )
    sqlite_session.add(board)
    lead = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="lead",
        status="online",
        openclaw_session_id="lead-session",
        is_board_lead=True,
    )
    sqlite_session.add(lead)
    await sqlite_session.commit()
    yield sqlite_session, board, lead


@pytest.mark.asyncio
async def test_count_actions_is_zero_for_silent_window(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    session, board, lead = seeded
    bookmark = datetime(2026, 4, 21, tzinfo=timezone.utc)
    assert (
        await count_lead_actions_since(
            session,
            agent_id=lead.id,
            board_id=board.id,
            bookmark=bookmark,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_blocker_creation_by_lead_counts_as_action(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    session, board, lead = seeded
    bookmark = datetime(2026, 4, 21, tzinfo=timezone.utc)
    session.add(
        Blocker(
            board_id=board.id,
            task_id=uuid4(),
            category="source",
            owner_role="frontend-dev",
            created_by_agent_id=lead.id,
        ),
    )
    await session.commit()
    assert (
        await count_lead_actions_since(
            session,
            agent_id=lead.id,
            board_id=board.id,
            bookmark=bookmark,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_comment_activity_does_not_count(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Pure commentary is the exact pattern §I5 wants to mark as no-op."""

    session, board, lead = seeded
    bookmark = datetime(2026, 4, 21, tzinfo=timezone.utc)
    session.add(
        ActivityEvent(
            event_type="task.comment",
            board_id=board.id,
            agent_id=lead.id,
            message="holding",
        ),
    )
    await session.commit()
    assert (
        await count_lead_actions_since(
            session,
            agent_id=lead.id,
            board_id=board.id,
            bookmark=bookmark,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_status_change_counts_as_action(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    session, board, lead = seeded
    bookmark = datetime(2026, 4, 21, tzinfo=timezone.utc)
    session.add(
        ActivityEvent(
            event_type="task.status_changed",
            board_id=board.id,
            agent_id=lead.id,
            message="review → done",
        ),
    )
    await session.commit()
    assert (
        await count_lead_actions_since(
            session,
            agent_id=lead.id,
            board_id=board.id,
            bookmark=bookmark,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_actions_by_other_agents_dont_count(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Attribution must be strict — another agent's action doesn't
    credit the lead."""

    session, board, _lead = seeded
    other_agent_id = uuid4()
    bookmark = datetime(2026, 4, 21, tzinfo=timezone.utc)
    session.add(
        ActivityEvent(
            event_type="task.status_changed",
            board_id=board.id,
            agent_id=other_agent_id,
            message="review → done",
        ),
    )
    await session.commit()
    # score the LEAD, not the other agent
    assert (
        await count_lead_actions_since(
            session,
            agent_id=_lead.id,
            board_id=board.id,
            bookmark=bookmark,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_first_sweep_emits_bootstrap_not_candidate(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Warmup grace: the very first sweep for a lead writes a
    bootstrap marker so subsequent sweeps have a bookmark, but
    doesn't emit a real no-op candidate — that would attribute
    the deploy-downtime window as a lead failure."""

    from app.services.shadow_metrics import (
        EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP,
    )

    session, board, lead = seeded
    fired = await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    assert fired is False
    events = (
        await session.exec(
            select(ShadowMetricEvent).where(
                col(ShadowMetricEvent.agent_id) == lead.id
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_type == EVENT_SUPERVISOR_HEARTBEAT_SCORING_BOOTSTRAP


@pytest.mark.asyncio
async def test_second_sweep_after_bootstrap_emits_noop_candidate(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Second sweep has a bookmark from the bootstrap; now a silent
    window produces a real candidate."""

    session, board, lead = seeded
    # First: bootstrap
    await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    # Second: real scoring
    fired = await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    assert fired is True
    candidates = (
        await session.exec(
            select(ShadowMetricEvent).where(
                col(ShadowMetricEvent.event_type)
                == EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE
            )
        )
    ).all()
    assert len(candidates) == 1
    assert candidates[0].agent_id == lead.id


@pytest.mark.asyncio
async def test_score_lead_once_skips_active_window(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    session, board, lead = seeded
    session.add(
        ActivityEvent(
            event_type="task.status_changed",
            board_id=board.id,
            agent_id=lead.id,
            message="review → done",
        ),
    )
    await session.commit()
    fired = await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    assert fired is False


@pytest.mark.asyncio
async def test_consecutive_noops_emit_streak_alert(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Three sweeps required: bootstrap (warmup), first real
    candidate, second real candidate (+ streak alert). Warmup
    intentionally doesn't count toward the streak so a boot-time
    idle window can't alert."""

    session, board, lead = seeded
    # 1st: bootstrap
    await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    # 2nd: first real no-op candidate (no streak yet)
    await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    # 3rd: second candidate + streak alert
    await score_lead_once(
        session,
        agent=lead,
        board_id=board.id,
        sweep_interval=timedelta(minutes=5),
    )
    candidates = (
        await session.exec(
            select(ShadowMetricEvent).where(
                col(ShadowMetricEvent.event_type)
                == EVENT_SUPERVISOR_HEARTBEAT_NOOP_CANDIDATE
            )
        )
    ).all()
    alerts = (
        await session.exec(
            select(ShadowMetricEvent).where(
                col(ShadowMetricEvent.event_type)
                == EVENT_SUPERVISOR_HEARTBEAT_NOOP_STREAK_ALERT
            )
        )
    ).all()
    assert len(candidates) == 2
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_score_all_leads_skips_boards_without_flag(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Boards without ``lead_scoring_v1`` are opted out."""

    session, board, _lead = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    emitted = await score_all_leads_once(
        session, sweep_interval=timedelta(minutes=5)
    )
    assert emitted == 0


@pytest.mark.asyncio
async def test_score_all_leads_only_scores_board_leads(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    """Non-lead agents on the same board are never scored."""

    session, board, _lead = seeded
    session.add(
        Agent(
            id=uuid4(),
            board_id=board.id,
            gateway_id=_lead.gateway_id,
            name="worker",
            status="online",
            openclaw_session_id="worker-session",
            is_board_lead=False,
        ),
    )
    await session.commit()
    # First pass: warmup — bootstrap, no candidate.
    emitted_first = await score_all_leads_once(
        session, sweep_interval=timedelta(minutes=5)
    )
    assert emitted_first == 0
    # Second pass: real scoring — exactly one lead, one candidate.
    emitted_second = await score_all_leads_once(
        session, sweep_interval=timedelta(minutes=5)
    )
    assert emitted_second == 1


@pytest.mark.asyncio
async def test_last_scoring_bookmark_null_for_unscored_agent(
    seeded: tuple[AsyncSession, Board, Agent],
) -> None:
    session, _board, lead = seeded
    assert await last_scoring_bookmark(session, agent_id=lead.id) is None
