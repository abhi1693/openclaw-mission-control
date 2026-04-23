# ruff: noqa: INP001
"""Part D.2 tests — auto-file operator Blocker on stale-agent-session."""

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
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.stale_agent_blocker import (
    StaleAgentGatewayReason,
    classify_gateway_error,
    file_stale_agent_blocker_if_configured,
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
# classify_gateway_error
# --------------------------------------------------------------------


def test_classifier_matches_pairing_required() -> None:
    assert (
        classify_gateway_error(
            OpenClawGatewayError("PAIRING_REQUIRED: scope upgrade needed")
        )
        == StaleAgentGatewayReason.PAIRING_REQUIRED
    )


def test_classifier_matches_stale_session_variants() -> None:
    for msg in (
        "Stale agent session — re-provision required",
        "Unknown agent 'frontend-dev'",
        "Agent removed from config",
    ):
        assert (
            classify_gateway_error(OpenClawGatewayError(msg))
            == StaleAgentGatewayReason.STALE_SESSION
        )


def test_classifier_returns_none_for_transient_errors() -> None:
    """Transient network / non-stale phrasings must not fire the
    hook. The bare ``agent not found`` substring collides with too
    many unrelated failure modes (dispatch typos, deleted rows,
    transient race) so the classifier intentionally excludes it."""

    for msg in (
        "connection reset by peer",
        "Agent not found in gateway config",  # too broad — false-positive guard
        "gateway temporarily unavailable",
    ):
        assert classify_gateway_error(OpenClawGatewayError(msg)) is None


def test_classifier_case_insensitive() -> None:
    assert (
        classify_gateway_error(OpenClawGatewayError("pairing required"))
        == StaleAgentGatewayReason.PAIRING_REQUIRED
    )


def test_classifier_matches_pairing_separator_variants() -> None:
    """Gateway wording drifts across releases — space, underscore,
    dash, and CamelCase variants all resolve to the same signal."""

    for msg in (
        "PAIRING_REQUIRED",
        "pairing required",
        "pairing-required",
        "PairingRequired",
    ):
        assert (
            classify_gateway_error(OpenClawGatewayError(msg))
            == StaleAgentGatewayReason.PAIRING_REQUIRED
        ), msg


# --------------------------------------------------------------------
# file_stale_agent_blocker_if_configured
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_files_blocker_on_stale_session_when_flag_enabled(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    session, board, task = seeded
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
    )
    assert blocker_id is not None
    blocker = (
        await session.exec(
            select(Blocker).where(col(Blocker.id) == blocker_id)
        )
    ).first()
    assert blocker is not None
    assert blocker.category == "operator"
    assert blocker.owner_role == "operator"
    assert "frontend-dev" in (blocker.required_artifact or "")
    assert blocker.citation is not None


@pytest.mark.asyncio
async def test_skips_when_board_flag_off(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    session, board, task = seeded
    board.rollout_flags = {}
    session.add(board)
    await session.commit()
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("PAIRING_REQUIRED"),
    )
    assert blocker_id is None


@pytest.mark.asyncio
async def test_skips_when_error_is_not_stale_session(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    session, board, task = seeded
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Gateway temporarily unavailable"),
    )
    assert blocker_id is None


@pytest.mark.asyncio
async def test_dedupes_on_same_task_agent(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Retry storms must not multiply Blocker rows. A second call
    against the same (task, agent) while the first is still open
    returns None without filing."""

    session, board, task = seeded
    first = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
    )
    second = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("PAIRING_REQUIRED"),
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
async def test_integrity_error_from_partial_unique_index_returns_none(
    seeded: tuple[AsyncSession, Board, Task],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forces the check-then-insert race by monkey-patching the EXISTS
    pre-check to False. The second INSERT must fail cleanly on
    ``uq_blockers_operator_artifact_open`` and return None."""

    from app.services import stale_agent_blocker as module

    session, board, task = seeded
    first = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
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
        module, "_open_stale_agent_blocker_exists", _always_false
    )

    second = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("PAIRING_REQUIRED"),
    )
    assert second is None


@pytest.mark.asyncio
async def test_citation_redacts_token_from_transport_error(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Transport-layer errors (``ConnectionError``/``WebSocketException``)
    stringify to include the gateway URL whose query is ``?token=<shared>``.
    The Blocker citation must not persist that token verbatim — it's
    operator-facing and gets written to a row any board member can read."""

    session, board, task = seeded
    leaky_message = (
        "Stale agent session reached via "
        "wss://gateway.local/ws?token=super-secret-123 (request_id=req-999)"
    )
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError(leaky_message),
    )
    assert blocker_id is not None
    blocker = await session.get(Blocker, blocker_id)
    assert blocker is not None
    citation = blocker.citation or ""
    assert "super-secret-123" not in citation
    assert "token=<redacted>" in citation
    # request_id stays — 4.20 operators want it for log correlation.
    assert "request_id=req-999" in citation


@pytest.mark.asyncio
async def test_non_dedupe_integrity_error_reraises(
    seeded: tuple[AsyncSession, Board, Task],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-dedupe constraint violations must re-raise so real bugs
    surface — only the specific partial unique index may be silenced."""

    from app.services import stale_agent_blocker as module

    session, board, task = seeded
    monkeypatch.setattr(module, "_CATEGORY_OPERATOR", "not_a_valid_category")

    with pytest.raises(Exception) as exc_info:
        await file_stale_agent_blocker_if_configured(
            session,
            board=board,
            task_id=task.id,
            agent_name="frontend-dev",
            exc=OpenClawGatewayError("Stale agent session"),
        )
    assert "constraint" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_resolved_blocker_does_not_block_new_file(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Once the operator resolves the previous Blocker, a recurrence
    of the same error should file a fresh one — the resolved row is
    audit, the new row is the current state."""

    from app.core.time import utcnow

    session, board, task = seeded
    first = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
    )
    assert first is not None
    blocker = await session.get(Blocker, first)
    assert blocker is not None
    blocker.resolved_at = utcnow()
    session.add(blocker)
    await session.commit()

    second = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
    )
    assert second is not None
    assert second != first
