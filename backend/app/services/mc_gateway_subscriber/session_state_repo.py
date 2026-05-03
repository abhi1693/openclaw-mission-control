"""Read/write functions for ``GatewaySessionState`` rows.

Module-level async functions over an injected ``AsyncSession`` —
matches the house style for ``app/services/*`` (blockers, lead_notify,
activity_log, parent_cascade) where data layers are flat function
namespaces, not classmethod-only repo classes. Earlier slices used a
``SessionStateRepo`` class; codex review of slices 4-5 flagged the
class as inconsistent with the rest of the codebase, so it's been
flattened with no functional change.

Caller owns the transaction (``await session.commit()``) so multiple
writes in one event-loop tick can share a transaction.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.time import utcnow
from app.db import crud
from app.models.gateway_session_state import GatewaySessionState
from app.services.mc_gateway_subscriber.session_state_projector import (
    SessionState,
)

_NON_PK_COLUMNS = (
    "session_id",
    "last_phase",
    "last_message_seq",
    "last_changed_at_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "channel",
    "aborted_last_run",
    "updated_at",
)


async def upsert_session_state(
    session,  # AsyncSession; annotated dynamically to keep import surface minimal
    state: SessionState,
) -> None:
    """Insert or overwrite the row keyed by
    ``(state.agent_id, state.session_label)`` in a single statement
    via ``INSERT ... ON CONFLICT (agent_id, session_label) DO UPDATE``.

    Atomic — no separate SELECT round-trip per event, and no
    application-side race window between get-then-mutate. Postgres and
    SQLite both expose the same ``on_conflict_do_update`` API on their
    dialect-specific ``Insert`` statement, so production and tests
    exercise identical semantics.

    Other dialects fall back to the lookup-then-create path via
    ``crud.get_or_create`` — preserves correctness if MC ever points
    at a non-PG/SQLite store, at the cost of the original two-trip
    round-trip behaviour. No production target uses anything else
    today.
    """
    payload = {
        "session_id": state.session_id,
        "last_phase": state.last_phase,
        "last_message_seq": state.last_message_seq,
        "last_changed_at_ms": state.last_changed_at_ms,
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "total_tokens": state.total_tokens,
        "channel": state.channel,
        "aborted_last_run": state.aborted_last_run,
        "updated_at": utcnow(),
    }
    dialect_name = session.bind.dialect.name if session.bind is not None else None
    if dialect_name == "postgresql":
        insert = pg_insert
    elif dialect_name == "sqlite":
        insert = sqlite_insert
    else:
        obj, created = await crud.get_or_create(
            session,
            GatewaySessionState,
            agent_id=state.agent_id,
            session_label=state.session_label,
            defaults=payload,
            commit=False,
            refresh=False,
        )
        if not created:
            crud.apply_updates(obj, payload)
        return

    stmt = insert(GatewaySessionState).values(
        agent_id=state.agent_id,
        session_label=state.session_label,
        **payload,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["agent_id", "session_label"],
        set_={col: getattr(stmt.excluded, col) for col in _NON_PK_COLUMNS},
    )
    await session.execute(stmt)


async def get_session_state(
    session,
    *,
    agent_id: str,
    session_label: str,
) -> GatewaySessionState | None:
    stmt = select(GatewaySessionState).where(
        GatewaySessionState.agent_id == agent_id,
        GatewaySessionState.session_label == session_label,
    )
    result = await session.exec(stmt)
    return result.scalar_one_or_none()


async def list_session_states_for_agent(
    session,
    *,
    agent_id: str,
) -> list[GatewaySessionState]:
    stmt = select(GatewaySessionState).where(
        GatewaySessionState.agent_id == agent_id,
    )
    result = await session.exec(stmt)
    return list(result.scalars().all())


async def list_all_session_states(session) -> list[GatewaySessionState]:
    stmt = select(GatewaySessionState)
    result = await session.exec(stmt)
    return list(result.scalars().all())


async def list_main_session_states_for_agent_ids(
    session,
    *,
    agent_ids: Iterable[str],
) -> dict[str, GatewaySessionState]:
    """Batched lookup of the ``main`` session row for each gateway
    agent_id. Used by the lead next-action handler to avoid N+1 over
    the in-progress task list. Returns a dict keyed by agent_id;
    agents with no projected row are simply absent from the result."""
    ids = list(agent_ids)
    if not ids:
        return {}
    stmt = select(GatewaySessionState).where(
        GatewaySessionState.agent_id.in_(ids),  # type: ignore[attr-defined]
        GatewaySessionState.session_label == "main",
    )
    result = await session.exec(stmt)
    return {row.agent_id: row for row in result.scalars().all()}


async def list_session_states_for_agent_ids(
    session,
    *,
    agent_ids: Iterable[str],
) -> list[GatewaySessionState]:
    """Batched lookup of every session_label row for each gateway
    agent_id. Used by the operator read endpoint to scope the result
    set to the caller's organization without leaking cross-org rows."""
    ids = list(agent_ids)
    if not ids:
        return []
    stmt = select(GatewaySessionState).where(
        GatewaySessionState.agent_id.in_(ids),  # type: ignore[attr-defined]
    )
    result = await session.exec(stmt)
    return list(result.scalars().all())
