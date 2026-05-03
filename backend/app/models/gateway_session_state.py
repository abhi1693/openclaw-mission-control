"""Persisted projection of OpenClaw gateway ``sessions.changed`` events.

One row per ``(agent_id, session_label)`` — the natural identity for an
agent's long-lived session bucket on the gateway. ``agent_id`` is stored
verbatim from the gateway's sessionKey (e.g. ``mc-<uuid>``,
``lead-<uuid>``, ``mc-gateway-<uuid>``) and is intentionally NOT
foreign-keyed to ``agents.id`` so we can observe gateway-internal
sessions (mc-gateway-*) that have no MC row, and so the projector
can write before the agents row exists during provisioning races.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class GatewaySessionState(QueryModel, table=True):
    """Latest-known state of a single gateway session bucket."""

    __tablename__ = "gateway_session_state"  # pyright: ignore[reportAssignmentType]

    agent_id: str = Field(primary_key=True)
    session_label: str = Field(primary_key=True)
    session_id: str | None = Field(default=None)
    last_phase: str | None = Field(default=None)
    last_message_seq: int | None = Field(default=None)
    # Gateway-source-of-truth millisecond timestamp from the
    # ``sessions.changed`` event. Used by the projector for the
    # last-write-wins guard so reconnect replays don't regress state.
    # ``sa_type=BigInteger`` matches the migration; ms-since-epoch
    # exceeds INT4 range so the default Integer mapping would silently
    # truncate after 2038 and fail tests with sane fixtures sooner.
    last_changed_at_ms: int = Field(index=True, sa_type=BigInteger)
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    total_tokens: int | None = Field(default=None)
    channel: str | None = Field(default=None)
    aborted_last_run: bool = Field(default=False)
    # MC's own wall-clock write timestamp; useful to spot subscriber
    # gaps independent of gateway clock skew.
    updated_at: datetime = Field(default_factory=utcnow)
