"""Read/write layer for ``GatewaySessionState`` rows.

Thin classmethods over an injected ``AsyncSession`` so the projector
stays free of session-management plumbing and the read endpoints
share the same callable surface. No business logic here — last-
write-wins ordering lives in the projector, not the repo.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from app.core.time import utcnow
from app.models.gateway_session_state import GatewaySessionState
from app.services.mc_gateway_subscriber.session_state_projector import (
    SessionState,
)


class SessionStateRepo:
    """Static-style repo (all classmethods) — no per-instance state to
    carry, and the explicit class scope makes call-sites greppable
    (`SessionStateRepo.upsert(...)`)."""

    @classmethod
    async def upsert(
        cls,
        session,  # AsyncSession; annotated dynamically to keep import surface minimal
        state: SessionState,
    ) -> None:
        """Insert or overwrite the row keyed by
        ``(state.agent_id, state.session_label)``. Caller is responsible
        for ``await session.commit()`` so multiple upserts in one event
        loop tick can share a transaction."""
        existing = await cls.get(
            session,
            agent_id=state.agent_id,
            session_label=state.session_label,
        )
        now = utcnow()
        if existing is None:
            row = GatewaySessionState(
                agent_id=state.agent_id,
                session_label=state.session_label,
                session_id=state.session_id,
                last_phase=state.last_phase,
                last_message_seq=state.last_message_seq,
                last_changed_at_ms=state.last_changed_at_ms,
                input_tokens=state.input_tokens,
                output_tokens=state.output_tokens,
                total_tokens=state.total_tokens,
                channel=state.channel,
                aborted_last_run=state.aborted_last_run,
                updated_at=now,
            )
            session.add(row)
            return
        existing.session_id = state.session_id
        existing.last_phase = state.last_phase
        existing.last_message_seq = state.last_message_seq
        existing.last_changed_at_ms = state.last_changed_at_ms
        existing.input_tokens = state.input_tokens
        existing.output_tokens = state.output_tokens
        existing.total_tokens = state.total_tokens
        existing.channel = state.channel
        existing.aborted_last_run = state.aborted_last_run
        existing.updated_at = now

    @classmethod
    async def get(
        cls,
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

    @classmethod
    async def list_for_agent(
        cls,
        session,
        *,
        agent_id: str,
    ) -> list[GatewaySessionState]:
        stmt = select(GatewaySessionState).where(
            GatewaySessionState.agent_id == agent_id,
        )
        result = await session.exec(stmt)
        return list(result.scalars().all())

    @classmethod
    async def list_all(cls, session) -> list[GatewaySessionState]:
        stmt = select(GatewaySessionState)
        result = await session.exec(stmt)
        return list(result.scalars().all())

    @classmethod
    async def list_main_for_agent_ids(
        cls,
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
