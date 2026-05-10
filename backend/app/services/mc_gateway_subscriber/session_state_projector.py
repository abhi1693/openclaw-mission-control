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

from app.services.openclaw.protocol_constants import AGENT_SESSION_PREFIX


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
    # Slice-6 lifecycle-projection fields captured from
    # ``sessions.changed`` events. ``parent_session_key`` links a child
    # session to its parent agent's session (null for top-level).
    #
    # ``last_lifecycle_reason`` — gateway 5.3 broadcast reason. 12
    # strings from 3 source files (every ``emitSessionLifecycleEvent``/
    # ``emitSessionsChanged`` call site): send / steer / create / patch /
    # new / reset / abort / delete / checkpoint-branch /
    # checkpoint-restore / compact (sessions.ts) + create
    # (subagent-spawn.ts, dedup) + subagent-status
    # (subagent-registry-lifecycle.ts). The ``endedReason`` enum
    # ("completed"/"expiry"/"spawn-failed"/"retry-limit"/"deleted") is
    # internal — hook payloads only, never on the wire. Note: ``delete``
    # (no ``d``) on the wire, NOT ``deleted``.
    #
    # ``last_status`` — per-run state from the broadcast payload
    # (sessions.ts:200 spreads ``status: sessionRow.status``). Live
    # values: running / done / failed / timed_out. THIS field
    # distinguishes success-vs-failure for ACP children under
    # ``reason="subagent-status"`` — match on terminal status, not
    # reason.
    parent_session_key: str | None = None
    last_status: str | None = None
    last_lifecycle_reason: str | None = None


_STABLE_SUB_LABELS = frozenset({"heartbeat"})


def parse_session_key(key: Any) -> tuple[str, str] | None:
    """Parse a gateway sessionKey into ``(agent_id, label)``.

    Accepts:

    * 3-segment keys ``agent:<agent_id>:<label>`` — the canonical form
      for top-level agent sessions (``main``, ``debug``, etc.).
    * 4-segment keys ``agent:<agent_id>:<label>:<sub>`` — but ONLY when
      ``<sub>`` is a known STABLE bucket (currently ``{"heartbeat"}``).
      Live capture (2026-05-03) showed lead/worker agents emit
      ``agent:lead-<board>:main:heartbeat`` for tick sessions; the
      label rides as ``"main:heartbeat"`` so the row gets its own bucket.

    Rejects:

    * 4-segment keys with non-allowlisted sub-labels — codex
      finding 2026-05-03: ``agent:<id>:acp:<uuid>`` (per-run ACP child
      cardinality, see ``acp-spawn.ts:1048``) would pollute the table
      with one row per ACP run AND evade cleanup_orphaned_session_states
      (the cleanup function only owns ``mc-/mc-gateway-/lead-`` prefixes).
      Add new stable sub-labels to ``_STABLE_SUB_LABELS`` as discovered.
    * 5+ segment keys — blocks cron-run sub-session keys
      ``agent:<id>:cron:<job>:run:<run>`` and 6-segment ACP binding keys
      from ``persistent-bindings.types.ts``.
    * Wrong namespace, empty parts, non-string input.
    """
    if not isinstance(key, str):
        return None
    parts = key.split(":")
    if len(parts) == 3:
        namespace, agent_id, label = parts
    elif len(parts) == 4:
        namespace, agent_id, label_main, label_sub = parts
        if label_sub not in _STABLE_SUB_LABELS:
            return None
        label = f"{label_main}:{label_sub}"
    else:
        return None
    if namespace != AGENT_SESSION_PREFIX or not agent_id or not label:
        return None
    return agent_id, label


def build_state_from_frame(frame: dict[str, Any]) -> SessionState | None:
    """Pure function: extract a ``SessionState`` from a sessions.changed
    event frame, or ``None`` if the frame is malformed / off-namespace.

    Shared by both projector implementations (in-memory + DB) so the
    parsing contract has exactly one source of truth. No side effects;
    no last-write-wins ordering — that lives in the projector callers
    that own the storage layer.
    """
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        return None

    parsed = parse_session_key(payload.get("sessionKey"))
    if parsed is None:
        return None
    agent_id, label = parsed

    ts = payload.get("ts")
    if not isinstance(ts, int):
        return None

    # The gateway emits two distinct sessions.changed shapes (verified
    # against live 5.3 capture + ``server-session-events.ts``):
    #
    # * Message-phase events: fields appear BOTH at the top of the
    #   inner payload AND nested under a ``session`` object (the
    #   nested copy is the legacy mirror that buildGatewaySessionSnapshot
    #   spreads into the top level).
    # * Lifecycle events (``reason`` set): only top-level — NO nested
    #   ``session`` object at all.
    #
    # Slice-4 read solely from ``session.<field>`` and silently dropped
    # data on every lifecycle event, then wrote None to the projection
    # row, clobbering the previously-correct values from prior message
    # events. Codex finding 2026-05-04. Read top-level first; fall back
    # to nested for backwards-compat with older 4.x event shapes.
    session = payload.get("session") or {}

    def _pick_str(field: str) -> str | None:
        return _optional_str(payload.get(field)) or _optional_str(session.get(field))

    def _pick_int(field: str) -> int | None:
        top = _optional_int(payload.get(field))
        if top is not None:
            return top
        return _optional_int(session.get(field))

    return SessionState(
        agent_id=agent_id,
        session_label=label,
        session_id=_pick_str("sessionId"),
        last_phase=_optional_str(payload.get("phase")),
        last_message_seq=_optional_int(payload.get("messageSeq")),
        last_changed_at_ms=ts,
        input_tokens=_pick_int("inputTokens"),
        output_tokens=_pick_int("outputTokens"),
        total_tokens=_pick_int("totalTokens"),
        channel=_pick_str("channel"),
        # Strict identity-compare to True: a string field carrying
        # "false" (or any non-empty string) is truthy under bool() and
        # would silently flip aborted_last_run to True. Mirror the
        # _optional_int defensive pattern.
        aborted_last_run=(
            payload.get("abortedLastRun") is True or session.get("abortedLastRun") is True
        ),
        # Slice-6 ACP-completion signals. Always top-level on lifecycle
        # events (server-session-events.ts createLifecycleEventBroadcastHandler).
        parent_session_key=_optional_str(payload.get("parentSessionKey")),
        last_status=_optional_str(payload.get("status")),
        last_lifecycle_reason=_optional_str(payload.get("reason")),
    )


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
        new_state = build_state_from_frame(frame)
        if new_state is None:
            return

        key = (new_state.agent_id, new_state.session_label)
        existing = self._state.get(key)
        if existing is not None and new_state.last_changed_at_ms <= existing.last_changed_at_ms:
            return

        # Slice-4 note (now realised by DbSessionStateProjector): when
        # wiring side-effects, diff against `existing` first — heartbeat
        # ticks emit sessions.changed every ~10s with identical field
        # values, so unguarded write/notify amplifies pointlessly.
        self._state[key] = new_state

    def get(self, agent_id: str) -> tuple[SessionState, ...]:
        """Return all session snapshots for ``agent_id`` (empty tuple if
        nothing recorded yet)."""
        return tuple(s for (aid, _), s in self._state.items() if aid == agent_id)

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
