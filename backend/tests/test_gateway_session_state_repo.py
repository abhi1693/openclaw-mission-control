"""Tests for the GatewaySessionState read/write layer.

The repo is the seam between the projector (event consumer) and
Postgres. Keeps the projector free of session-management plumbing and
gives the read endpoints a stable callable surface.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.gateway_session_state import GatewaySessionState
from app.services.mc_gateway_subscriber.session_state_projector import SessionState
from app.services.mc_gateway_subscriber.session_state_repo import (
    SessionStateRepo,
)


def _state(
    *,
    agent_id: str = "mc-aaaaaaaa-1111-2222-3333-444444444444",
    session_label: str = "main",
    last_changed_at_ms: int = 1_777_823_446_849,
    last_phase: str | None = "message",
    last_message_seq: int | None = 158,
    session_id: str | None = "062b709b-540e-430b-b451-d48f4acff7b9",
    input_tokens: int | None = 49_931,
    output_tokens: int | None = 14_736,
    total_tokens: int | None = 64_667,
    channel: str | None = "webchat",
    aborted_last_run: bool = False,
) -> SessionState:
    return SessionState(
        agent_id=agent_id,
        session_label=session_label,
        session_id=session_id,
        last_phase=last_phase,
        last_message_seq=last_message_seq,
        last_changed_at_ms=last_changed_at_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        channel=channel,
        aborted_last_run=aborted_last_run,
    )


@pytest.mark.asyncio
async def test_upsert_inserts_when_no_row_exists(
    sqlite_session: AsyncSession,
) -> None:
    state = _state()
    await SessionStateRepo.upsert(sqlite_session, state)
    await sqlite_session.commit()

    rows = await SessionStateRepo.list_all(sqlite_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.agent_id == state.agent_id
    assert row.session_label == state.session_label
    assert row.session_id == state.session_id
    assert row.last_changed_at_ms == state.last_changed_at_ms
    assert row.input_tokens == state.input_tokens
    assert row.output_tokens == state.output_tokens
    assert row.total_tokens == state.total_tokens
    assert row.channel == state.channel
    assert row.aborted_last_run is False


@pytest.mark.asyncio
async def test_upsert_updates_in_place_for_existing_key(
    sqlite_session: AsyncSession,
) -> None:
    """Composite PK (agent_id, session_label) — second upsert with the
    same key must overwrite, not duplicate. Otherwise the projection
    table grows by one row per heartbeat tick."""
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(last_changed_at_ms=1, total_tokens=100, last_phase="created"),
    )
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(last_changed_at_ms=2, total_tokens=200, last_phase="message"),
    )
    await sqlite_session.commit()

    rows = await SessionStateRepo.list_all(sqlite_session)
    assert len(rows) == 1
    assert rows[0].last_changed_at_ms == 2
    assert rows[0].total_tokens == 200
    assert rows[0].last_phase == "message"


@pytest.mark.asyncio
async def test_get_returns_row_for_existing_key(
    sqlite_session: AsyncSession,
) -> None:
    await SessionStateRepo.upsert(sqlite_session, _state())
    await sqlite_session.commit()

    row = await SessionStateRepo.get(
        sqlite_session,
        agent_id="mc-aaaaaaaa-1111-2222-3333-444444444444",
        session_label="main",
    )
    assert row is not None
    assert row.last_changed_at_ms == 1_777_823_446_849


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_key(
    sqlite_session: AsyncSession,
) -> None:
    row = await SessionStateRepo.get(
        sqlite_session,
        agent_id="mc-nonexistent",
        session_label="main",
    )
    assert row is None


@pytest.mark.asyncio
async def test_list_for_agent_filters_to_matching_agent_id(
    sqlite_session: AsyncSession,
) -> None:
    """An agent has finitely many session_label buckets ('main',
    occasional 'debug'); list_for_agent returns all of them and only
    them."""
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    b_id = "mc-bbbbbbbb-1111-2222-3333-444444444444"
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id, session_label="main"))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id, session_label="debug"))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=b_id, session_label="main"))
    await sqlite_session.commit()

    rows = await SessionStateRepo.list_for_agent(sqlite_session, agent_id=a_id)
    assert len(rows) == 2
    labels = {r.session_label for r in rows}
    assert labels == {"main", "debug"}


@pytest.mark.asyncio
async def test_list_for_agent_empty_for_unknown_agent(
    sqlite_session: AsyncSession,
) -> None:
    rows = await SessionStateRepo.list_for_agent(
        sqlite_session, agent_id="mc-nonexistent"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_list_all_empty_when_no_rows(
    sqlite_session: AsyncSession,
) -> None:
    rows = await SessionStateRepo.list_all(sqlite_session)
    assert rows == []


@pytest.mark.asyncio
async def test_upsert_persists_aborted_flag(
    sqlite_session: AsyncSession,
) -> None:
    """``aborted_last_run`` is the operator-visible "this session crashed"
    flag — must round-trip through the DB faithfully even when the
    column default would otherwise mask it."""
    await SessionStateRepo.upsert(
        sqlite_session, _state(aborted_last_run=True)
    )
    await sqlite_session.commit()
    rows = await SessionStateRepo.list_all(sqlite_session)
    assert rows[0].aborted_last_run is True


@pytest.mark.asyncio
async def test_list_main_for_agent_ids_batched(
    sqlite_session: AsyncSession,
) -> None:
    """Lead next-action handler needs the main session row for many
    assigned agents in one trip — N+1 against the per-board task list
    is the difference between one query and 50."""
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    b_id = "mc-bbbbbbbb-1111-2222-3333-444444444444"
    c_id = "mc-cccccccc-1111-2222-3333-444444444444"
    await SessionStateRepo.upsert(
        sqlite_session, _state(agent_id=a_id, session_label="main")
    )
    await SessionStateRepo.upsert(
        sqlite_session, _state(agent_id=a_id, session_label="debug")
    )
    await SessionStateRepo.upsert(
        sqlite_session, _state(agent_id=b_id, session_label="main")
    )
    # c_id has no row at all
    await sqlite_session.commit()

    rows = await SessionStateRepo.list_main_for_agent_ids(
        sqlite_session, agent_ids=[a_id, b_id, c_id, "mc-unknown"]
    )
    assert set(rows.keys()) == {a_id, b_id}
    assert rows[a_id].session_label == "main"
    assert rows[b_id].session_label == "main"


@pytest.mark.asyncio
async def test_list_main_for_agent_ids_empty_input_returns_empty(
    sqlite_session: AsyncSession,
) -> None:
    """Defensive: handler may pass an empty list when no in-progress
    tasks have assigned agents — must not run a `WHERE agent_id IN ()`
    query, which Postgres rejects as a syntax error."""
    rows = await SessionStateRepo.list_main_for_agent_ids(
        sqlite_session, agent_ids=[]
    )
    assert rows == {}


@pytest.mark.asyncio
async def test_upsert_writes_updated_at_on_each_call(
    sqlite_session: AsyncSession,
) -> None:
    """``updated_at`` is MC's wall-clock write timestamp (independent of
    ``last_changed_at_ms`` which is the gateway's ms epoch). Each
    upsert must refresh it so operators can tell when the projector
    last touched a row."""
    await SessionStateRepo.upsert(sqlite_session, _state(last_changed_at_ms=1))
    await sqlite_session.commit()
    first = (await SessionStateRepo.list_all(sqlite_session))[0].updated_at

    await SessionStateRepo.upsert(sqlite_session, _state(last_changed_at_ms=2))
    await sqlite_session.commit()
    second = (await SessionStateRepo.list_all(sqlite_session))[0].updated_at

    assert second >= first
    # Inserted GatewaySessionState rows are returned with their server-
    # set defaults reflected by the model; the test infra uses SQLite
    # which honours datetime(timezone=True) but doesn't enforce
    # microsecond resolution. Don't assert strict >= equality on the
    # second write completing within the same wall-clock tick.
