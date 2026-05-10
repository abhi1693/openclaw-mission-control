"""Postgres-backed projector for ``sessions.changed`` event frames.

Drop-in replacement for the in-memory ``SessionStateProjector`` in the
worker entry point. Enforces last-write-wins ts ordering before each
write so reconnect-replay snapshots can't regress persisted state.

Earlier slices also carried a "skip if every projected field equals
the existing row" diff guard intended to cut heartbeat-tick write
amplification. Codex review surfaced that the guard breaks ordering:
when a same-field newer event is dropped, the persisted ``last_changed_at_ms``
stays at the older value, so a later out-of-order frame with truly
older content but a slightly newer ts than the persisted one can
pass the ts compare and overwrite the row with stale state. At the
real event rate (~1 event per agent per 10s heartbeat) the saved
write is trivially cheap, so the guard is gone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.mc_gateway_subscriber.session_state_projector import (
    build_state_from_frame,
)
from app.services.mc_gateway_subscriber.session_state_repo import (
    get_session_state,
    upsert_session_state,
)


class DbSessionStateProjector:
    """Persisting projector. ``session_factory`` returns an async context
    manager yielding an ``AsyncSession`` — usually the production
    ``async_sessionmaker`` from ``app.db.session``."""

    def __init__(self, *, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def __call__(self, frame: dict[str, Any]) -> None:
        new_state = build_state_from_frame(frame)
        if new_state is None:
            return

        async with self._session_factory() as session:
            existing = await get_session_state(
                session,
                agent_id=new_state.agent_id,
                session_label=new_state.session_label,
            )
            if existing is not None and new_state.last_changed_at_ms <= existing.last_changed_at_ms:
                return
            await upsert_session_state(session, new_state)
            await session.commit()
