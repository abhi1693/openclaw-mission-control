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
    extract_request_id,
    file_stale_agent_blocker_if_configured,
    request_id_from_exc,
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


# --------------------------------------------------------------------
# Part E.4: request_id extraction into Blocker.citation_request_id
# --------------------------------------------------------------------


def test_extract_request_id_handles_paren_equals_format() -> None:
    """Canonical 4.20+ shape: ``... (request_id=req-abc-123)``."""

    assert (
        extract_request_id(
            "PAIRING_REQUIRED: scope upgrade needed (request_id=req-abc-123)"
        )
        == "req-abc-123"
    )


def test_extract_request_id_handles_colon_format() -> None:
    """Also accept ``request_id: <val>`` for gateway builds that drop
    the equals in favor of key-value style."""

    assert (
        extract_request_id(
            "Stale agent session. request_id: req-xyz-789"
        )
        == "req-xyz-789"
    )


def test_extract_request_id_handles_camel_case() -> None:
    """Some gateway builds emit ``requestId`` (camelCase). Accept both."""

    assert (
        extract_request_id("PAIRING_REQUIRED (requestId=req-CAM-1)")
        == "req-CAM-1"
    )


def test_extract_request_id_returns_none_on_absence() -> None:
    """4.19 and earlier don't embed the id — extractor must return None."""

    assert extract_request_id("Stale agent session — no hint") is None


@pytest.mark.asyncio
async def test_filer_stamps_request_id_on_blocker(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """End-to-end: 4.20+ error message → filer → Blocker row with the
    structured column populated AND the id preserved in the citation."""

    session, board, task = seeded
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError(
            "PAIRING_REQUIRED: re-pair required for frontend-dev "
            "(request_id=req-live-001)"
        ),
    )
    assert blocker_id is not None
    blocker = await session.get(Blocker, blocker_id)
    assert blocker is not None
    assert blocker.citation_request_id == "req-live-001"
    # Citation retains the id too — structured field is additive.
    assert "req-live-001" in (blocker.citation or "")


@pytest.mark.asyncio
async def test_filer_leaves_request_id_null_on_4_19_error(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """Older-gateway message without the id must produce a Blocker with
    ``citation_request_id=None`` — NULL is the signal "no id available"
    for operator triage."""

    session, board, task = seeded
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=OpenClawGatewayError("Stale agent session"),
    )
    assert blocker_id is not None
    blocker = await session.get(Blocker, blocker_id)
    assert blocker is not None
    assert blocker.citation_request_id is None


def test_request_id_from_exc_prefers_structured_details() -> None:
    """The 4.20+ gateway protocol carries ``requestId`` in
    ``data["error"]``. ``request_id_from_exc`` must read that
    structured field ahead of any regex parse — the message string
    is a fallback surface only."""

    exc = OpenClawGatewayError(
        "PAIRING_REQUIRED: re-pair needed",
        details={
            "code": "PAIRING_REQUIRED",
            "requestId": "req-structured-999",
            "reason": "scope-upgrade",
        },
    )
    assert request_id_from_exc(exc) == "req-structured-999"


def test_request_id_from_exc_falls_back_to_regex_when_no_details() -> None:
    """Pre-4.20 errors arrive with no structured ``details``; the
    regex-over-message path still wins the id for old builds."""

    exc = OpenClawGatewayError(
        "PAIRING_REQUIRED: scope upgrade needed (request_id=req-old-1)"
    )
    assert request_id_from_exc(exc) == "req-old-1"


def test_request_id_from_exc_returns_none_when_absent_in_both_paths() -> None:
    exc = OpenClawGatewayError("Stale agent session — no remediation hint")
    assert request_id_from_exc(exc) is None


@pytest.mark.asyncio
async def test_filer_prefers_structured_request_id_over_message_parse(
    seeded: tuple[AsyncSession, Board, Task],
) -> None:
    """When ``OpenClawGatewayError.details`` carries ``requestId``, the
    filer must stamp that verbatim — never re-parse the human message
    (which might have been redacted, truncated, or rewritten)."""

    session, board, task = seeded
    exc = OpenClawGatewayError(
        # Message deliberately carries a DIFFERENT id than structured.
        "PAIRING_REQUIRED: scope upgrade (request_id=req-FROM-MSG)",
        details={
            "code": "PAIRING_REQUIRED",
            "requestId": "req-FROM-STRUCTURED",
        },
    )
    blocker_id = await file_stale_agent_blocker_if_configured(
        session,
        board=board,
        task_id=task.id,
        agent_name="frontend-dev",
        exc=exc,
    )
    assert blocker_id is not None
    blocker = await session.get(Blocker, blocker_id)
    assert blocker is not None
    assert blocker.citation_request_id == "req-FROM-STRUCTURED"
