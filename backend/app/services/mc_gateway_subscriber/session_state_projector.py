"""First gateway-event projector.

Consumes ``sessions.changed`` events from the OpenClaw gateway (via the
long-lived ``Subscriber``) and maintains an in-memory map of per-session
runtime state keyed by ``(agent_id, session_label)``. MC API endpoints
read from a shared instance to surface real-time session activity in
lead signals (e.g. ``/agent/next-action``).

Design notes:

* The projector is intentionally process-local with no persistence.
  Slice 4 will add a persistence adapter; keeping the contract minimal
  here means the API layer can ship against the in-memory store and
  switch storage transparently later.
* The handler MUST NOT raise. The dispatcher in ``Subscriber`` already
  swallows exceptions, but a quiet drop is preferable to spamming the
  log on every malformed event — and we want to keep the connection
  healthy even when the gateway emits new event variants we haven't
  modelled yet.
* Out-of-order events are dropped (last-write-wins by ``ts``). Without
  this guard, a reconnect that replays an older snapshot would make
  lead signals flap between stale and current state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.openclaw.constants import AGENT_SESSION_PREFIX


@dataclass(frozen=True)
class SessionState:
    """Per-session snapshot derived from the latest ``sessions.changed``
    event for a given ``(agent_id, session_label)``."""

    agent_id: str
    session_label: str
    session_id: str | None
    last_phase: str | None
    last_message_seq: int | None
    last_changed_at_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    channel: str | None
    aborted_last_run: bool


def parse_session_key(key: Any) -> tuple[str, str] | None:
    """Parse a gateway sessionKey of the form ``agent:<agent_id>:<label>``.

    Returns ``(agent_id, label)`` on success, ``None`` for any input
    that doesn't match the expected shape (wrong namespace, missing
    parts, empty fields, non-string).
    """
    if not isinstance(key, str):
        return None
    parts = key.split(":")
    if len(parts) != 3:
        return None
    namespace, agent_id, label = parts
    if namespace != AGENT_SESSION_PREFIX or not agent_id or not label:
        return None
    return agent_id, label


@dataclass
class SessionStateProjector:
    """In-memory projector for ``sessions.changed`` events."""

    _state: dict[tuple[str, str], SessionState] = field(default_factory=dict)

    async def __call__(self, frame: dict[str, Any]) -> None:
        """Apply one ``sessions.changed`` event frame. The Subscriber
        dispatcher hands handlers the full frame ``{type, event, payload,
        seq}``; the projector unwraps ``frame["payload"]`` internally so
        it can be wired directly via
        ``Subscriber.on('sessions.changed', projector)``."""
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return

        session_key = payload.get("sessionKey")
        parsed = parse_session_key(session_key)
        if parsed is None:
            return
        agent_id, label = parsed

        ts = payload.get("ts")
        if not isinstance(ts, int):
            return

        existing = self._state.get((agent_id, label))
        if existing is not None and ts <= existing.last_changed_at_ms:
            return

        session = payload.get("session") or {}
        new_state = SessionState(
            agent_id=agent_id,
            session_label=label,
            session_id=_optional_str(session.get("sessionId")),
            last_phase=_optional_str(payload.get("phase")),
            last_message_seq=_optional_int(payload.get("messageSeq")),
            last_changed_at_ms=ts,
            input_tokens=_optional_int(session.get("inputTokens")),
            output_tokens=_optional_int(session.get("outputTokens")),
            total_tokens=_optional_int(session.get("totalTokens")),
            channel=_optional_str(session.get("channel")),
            aborted_last_run=bool(session.get("abortedLastRun", False)),
        )
        # Slice 4 note: when wiring side-effects here (DB write, fan-out
        # callback), diff `new_state` against `existing` first — heartbeat
        # ticks emit sessions.changed every ~10s with the same field
        # values and would otherwise cause write/notify amplification.
        self._state[(agent_id, label)] = new_state

    def get(self, agent_id: str) -> tuple[SessionState, ...]:
        """Return all session snapshots for ``agent_id`` (empty tuple if
        nothing recorded yet)."""
        return tuple(
            s for (aid, _), s in self._state.items() if aid == agent_id
        )

    def snapshot(self) -> tuple[SessionState, ...]:
        """Return all currently-projected session snapshots. The
        returned tuple is immutable; the internal keying scheme (dict
        keyed by ``(agent_id, session_label)``) is an implementation
        detail and not exposed."""
        return tuple(self._state.values())


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int | None:
    # bool is a subclass of int in Python; reject so a mistyped gateway
    # field carrying True/False doesn't silently become 1/0 token counts.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
