"""Tests for ``GET /api/v1/gateways/projected-sessions``.

Reads the gateway_session_state projection table populated by the
mc_gateway_subscriber worker. Operator-scoped (require_org_admin) so
the lead/agent path can stay unchanged for slice 5.

Tests invoke the route handler directly against a sqlite session —
auth is exercised by the existing pattern in
``test_openclaw_runtime_status.py`` and a duplicate full-stack test
would only re-prove FastAPI dependency resolution.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.gateway import projected_gateway_sessions
from app.services.mc_gateway_subscriber.session_state_projector import SessionState
from app.services.mc_gateway_subscriber.session_state_repo import SessionStateRepo


def _state(
    *,
    agent_id: str = "mc-aaaaaaaa-1111-2222-3333-444444444444",
    session_label: str = "main",
    last_changed_at_ms: int = 1_777_823_446_849,
    last_phase: str | None = "message",
    total_tokens: int | None = 64_667,
    aborted_last_run: bool = False,
) -> SessionState:
    return SessionState(
        agent_id=agent_id,
        session_label=session_label,
        session_id="062b709b-540e-430b-b451-d48f4acff7b9",
        last_phase=last_phase,
        last_message_seq=158,
        last_changed_at_ms=last_changed_at_ms,
        input_tokens=49_931,
        output_tokens=14_736,
        total_tokens=total_tokens,
        channel="webchat",
        aborted_last_run=aborted_last_run,
    )


@pytest.mark.asyncio
async def test_projected_sessions_returns_empty_list_when_table_empty(
    sqlite_session: AsyncSession,
) -> None:
    response = await projected_gateway_sessions(
        agent_id=None,
        session=sqlite_session,
    )
    assert response.sessions == []


@pytest.mark.asyncio
async def test_projected_sessions_returns_all_rows_when_no_filter(
    sqlite_session: AsyncSession,
) -> None:
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    b_id = "mc-bbbbbbbb-1111-2222-3333-444444444444"
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=b_id))
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None,
        session=sqlite_session,
    )
    assert len(response.sessions) == 2
    assert {s.agent_id for s in response.sessions} == {a_id, b_id}


@pytest.mark.asyncio
async def test_projected_sessions_filters_by_agent_id(
    sqlite_session: AsyncSession,
) -> None:
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    b_id = "mc-bbbbbbbb-1111-2222-3333-444444444444"
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id, session_label="main"))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id, session_label="debug"))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=b_id, session_label="main"))
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=a_id,
        session=sqlite_session,
    )
    assert len(response.sessions) == 2
    assert all(s.agent_id == a_id for s in response.sessions)
    assert {s.session_label for s in response.sessions} == {"main", "debug"}


@pytest.mark.asyncio
async def test_projected_sessions_returns_empty_for_unknown_agent_filter(
    sqlite_session: AsyncSession,
) -> None:
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(agent_id="mc-aaaaaaaa-1111-2222-3333-444444444444"),
    )
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id="mc-nonexistent",
        session=sqlite_session,
    )
    assert response.sessions == []


@pytest.mark.asyncio
async def test_projected_sessions_round_trips_all_fields(
    sqlite_session: AsyncSession,
) -> None:
    """Schema mirrors the model — verify every field a slice-5 lead-
    signal consumer might read survives the API serialization."""
    state = _state(
        last_phase="message",
        total_tokens=10_000,
        aborted_last_run=True,
    )
    await SessionStateRepo.upsert(sqlite_session, state)
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None,
        session=sqlite_session,
    )
    assert len(response.sessions) == 1
    row = response.sessions[0]
    assert row.agent_id == state.agent_id
    assert row.session_label == state.session_label
    assert row.session_id == state.session_id
    assert row.last_phase == "message"
    assert row.last_message_seq == 158
    assert row.last_changed_at_ms == state.last_changed_at_ms
    assert row.input_tokens == state.input_tokens
    assert row.output_tokens == state.output_tokens
    assert row.total_tokens == 10_000
    assert row.channel == "webchat"
    assert row.aborted_last_run is True
    assert row.updated_at is not None
