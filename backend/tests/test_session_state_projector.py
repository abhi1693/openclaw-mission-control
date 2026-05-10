"""Tests for the first gateway-event projector.

The projector consumes ``sessions.changed`` events emitted by the
OpenClaw gateway and maintains an in-memory map of per-session state
keyed by ``(agent_id, session_label)``. MC API endpoints (slice 4) read
from the same projector instance to surface real-time session activity
in lead signals (e.g. ``/agent/next-action``).

These tests pin down the projection contract so the implementation
cannot drift silently from what the gateway actually emits — payload
shapes were captured live from .60 on 2026-05-01 and the field set
follows that capture.
"""

from __future__ import annotations

import pytest

from app.services.mc_gateway_subscriber.session_state_projector import (
    SessionState,
    SessionStateProjector,
    parse_session_key,
)

# ---------------------------------------------------------------------------
# parse_session_key — pure helper
# ---------------------------------------------------------------------------


def test_parse_session_key_extracts_agent_and_label() -> None:
    """Canonical gateway session keys follow ``agent:<agent_id>:<label>``
    where ``agent_id`` is the MC-side identifier (``mc-<uuid>`` /
    ``lead-<uuid>`` / ``mc-gateway-<uuid>``) and ``label`` is the
    per-agent session bucket (typically ``main``)."""
    assert parse_session_key("agent:mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66:main") == (
        "mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66",
        "main",
    )


def test_parse_session_key_supports_lead_and_gateway_prefixes() -> None:
    assert parse_session_key("agent:lead-aaaa1234-1111-2222-3333-444444444444:main") == (
        "lead-aaaa1234-1111-2222-3333-444444444444",
        "main",
    )
    assert parse_session_key("agent:mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e:main") == (
        "mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e",
        "main",
    )


def test_parse_session_key_supports_non_main_label() -> None:
    """Some sessions use labels other than ``main`` (e.g. side-channel
    bots). The parser must not hard-code the label."""
    assert parse_session_key("agent:mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66:debug") == (
        "mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66",
        "debug",
    )


def test_parse_session_key_accepts_4_segment_sub_label() -> None:
    """Live capture (2026-05-03) showed lead and worker agents emit
    4-segment session keys for sub-runs, e.g.
    ``agent:lead-<board>:main:heartbeat`` for heartbeat tick sessions.
    Slice-3 parser dropped these as malformed and the projector silently
    missed them. Treat the trailing ``:heartbeat`` as part of the label
    so the row IS captured under its full discriminator. ``heartbeat``
    is on the ``_STABLE_SUB_LABELS`` allowlist; per-run sub-labels
    (e.g. ``acp:<uuid>``) are rejected separately."""
    assert parse_session_key("agent:lead-05002170-201b-4c66-bae1-26c0c833f206:main:heartbeat") == (
        "lead-05002170-201b-4c66-bae1-26c0c833f206",
        "main:heartbeat",
    )
    assert parse_session_key("agent:mc-3461451b-5824-4ed0-872c-d14d5d2be107:debug:heartbeat") == (
        "mc-3461451b-5824-4ed0-872c-d14d5d2be107",
        "debug:heartbeat",
    )


@pytest.mark.parametrize(
    "key",
    [
        "",
        "not-an-agent-key",
        "agent:",
        "agent:mc-dd1abee5",  # missing label
        "session:foo:bar",  # wrong namespace
        "agent::main",  # empty agent_id
    ],
)
def test_parse_session_key_returns_none_for_unparseable_keys(key: str) -> None:
    assert parse_session_key(key) is None


def test_parse_session_key_drops_per_run_acp_child_keys() -> None:
    """Codex finding 2026-05-03: gateway's ``acp-spawn.ts:1048`` builds
    child keys as ``agent:<id>:acp:<uuid>`` — per-run cardinality.
    A naive 4-segment-accepts parser captured one projection row per
    ACP run AND those rows evade ``cleanup_orphaned_session_states``
    because the cleanup namespace allowlist is mc-/mc-gateway-/lead-.
    Verify per-run ACP child keys are dropped at the parser."""
    assert parse_session_key("agent:claude:acp:019de388-26cb-79e0-95f5-72a424d8e152") is None
    assert parse_session_key("agent:codex:acp:019ddc4c-b027-7ce0-9e49-aa10435bea59") is None


def test_parse_session_key_drops_cron_run_keys() -> None:
    """Live capture (2026-05-01) showed gateway emits cron-run sub-session
    keys of the form ``agent:<agent_id>:cron:<job_id>:run:<run_id>``.
    These represent individual scheduled-job invocations, not the
    long-lived agent-main session we want for lead signals — drop them
    so the projector doesn't pollute its state with one ephemeral row
    per heartbeat tick. Slice 4 may model cron-runs separately."""
    cron_key = (
        "agent:mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e"
        ":cron:2f098c3f-8f78-4bfc-9531-573f8782ef43"
        ":run:1483d56b-49cf-4261-aace-4918dfcf69c9"
    )
    assert parse_session_key(cron_key) is None


def test_parse_session_key_returns_none_for_non_string() -> None:
    """Defensive: gateway is trusted but a malformed payload should not
    crash the dispatcher."""
    assert parse_session_key(None) is None  # type: ignore[arg-type]
    assert parse_session_key(123) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SessionStateProjector — applies sessions.changed events
# ---------------------------------------------------------------------------


def _make_event(
    *,
    session_key: str = "agent:mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66:main",
    phase: str = "message",
    ts: int = 1_777_823_446_849,
    message_seq: int | None = 158,
    session_id: str = "062b709b-540e-430b-b451-d48f4acff7b9",
    input_tokens: int | None = 49_931,
    output_tokens: int | None = 14_736,
    total_tokens: int | None = 64_667,
    channel: str = "webchat",
    display_name: str = "webchat:g-agent-mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66-main",
    label: str = "QA-E2E",
    aborted_last_run: bool = False,
    parent_session_key: str | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> dict:
    """Build a sessions.changed event frame that mirrors the live
    gateway capture (see /tmp/probe_out.txt sample). The Subscriber
    dispatcher hands handlers the full frame, so the projector must see
    the same shape in tests as in production. Fields not under test are
    populated with realistic defaults."""
    inner: dict = {
        "sessionKey": session_key,
        "phase": phase,
        "ts": ts,
        "session": {
            "key": session_key,
            "kind": "direct",
            "label": label,
            "displayName": display_name,
            "channel": channel,
            "sessionId": session_id,
            "abortedLastRun": aborted_last_run,
            "updatedAt": ts,
        },
    }
    if parent_session_key is not None:
        inner["parentSessionKey"] = parent_session_key
    if status is not None:
        inner["status"] = status
    if reason is not None:
        inner["reason"] = reason
    if message_seq is not None:
        inner["messageSeq"] = message_seq
        inner["messageId"] = "0c51db90"
    if input_tokens is not None:
        inner["session"]["inputTokens"] = input_tokens
    if output_tokens is not None:
        inner["session"]["outputTokens"] = output_tokens
    if total_tokens is not None:
        inner["session"]["totalTokens"] = total_tokens
    return {
        "type": "event",
        "event": "sessions.changed",
        "payload": inner,
        "seq": 1,
    }


@pytest.mark.asyncio
async def test_projector_starts_empty() -> None:
    p = SessionStateProjector()
    assert p.snapshot() == ()
    assert p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66") == ()


@pytest.mark.asyncio
async def test_projector_records_first_event() -> None:
    p = SessionStateProjector()
    await p(_make_event())
    states = p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66")
    assert len(states) == 1
    s = states[0]
    assert isinstance(s, SessionState)
    assert s.agent_id == "mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66"
    assert s.session_label == "main"
    assert s.session_id == "062b709b-540e-430b-b451-d48f4acff7b9"
    assert s.last_phase == "message"
    assert s.last_message_seq == 158
    assert s.last_changed_at_ms == 1_777_823_446_849
    assert s.input_tokens == 49_931
    assert s.output_tokens == 14_736
    assert s.total_tokens == 64_667
    assert s.channel == "webchat"
    assert s.aborted_last_run is False


@pytest.mark.asyncio
async def test_projector_updates_existing_session_in_place() -> None:
    """A subsequent event for the same (agent_id, session_label) key must
    overwrite the row, not duplicate it."""
    p = SessionStateProjector()
    await p(_make_event(ts=1, message_seq=10, total_tokens=100))
    await p(_make_event(ts=2, phase="tool", message_seq=11, total_tokens=200))
    states = p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66")
    assert len(states) == 1
    assert states[0].last_changed_at_ms == 2
    assert states[0].last_phase == "tool"
    assert states[0].last_message_seq == 11
    assert states[0].total_tokens == 200


@pytest.mark.asyncio
async def test_projector_drops_event_with_older_or_equal_timestamp() -> None:
    """Events can arrive out of order across reconnects. The projector
    must not regress to an older snapshot when a later event has already
    been applied — otherwise lead signals would flap."""
    p = SessionStateProjector()
    await p(_make_event(ts=200, message_seq=20, total_tokens=2000))
    await p(_make_event(ts=100, message_seq=10, total_tokens=1000))
    states = p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66")
    assert states[0].last_changed_at_ms == 200
    assert states[0].last_message_seq == 20
    assert states[0].total_tokens == 2000


@pytest.mark.asyncio
async def test_projector_tracks_multiple_sessions_per_agent() -> None:
    p = SessionStateProjector()
    agent_id = "mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66"
    await p(_make_event(session_key=f"agent:{agent_id}:main"))
    await p(_make_event(session_key=f"agent:{agent_id}:debug"))
    states = p.get(agent_id)
    labels = {s.session_label for s in states}
    assert labels == {"main", "debug"}


@pytest.mark.asyncio
async def test_projector_ignores_unparseable_session_key() -> None:
    """A malformed sessionKey must not raise — the projector is on the
    hot dispatch path and one bad event would otherwise tear down the
    whole subscriber connection on the next handler exception."""
    p = SessionStateProjector()
    await p(_make_event(session_key="not-an-agent-key"))
    assert p.snapshot() == ()


@pytest.mark.asyncio
async def test_projector_ignores_frame_with_no_payload() -> None:
    """The dispatcher passes the full frame; a frame missing the inner
    ``payload`` dict (or with a non-dict value) must be silently
    dropped."""
    p = SessionStateProjector()
    await p({"type": "event", "event": "sessions.changed", "seq": 1})
    await p({"type": "event", "event": "sessions.changed", "payload": None})
    await p({"type": "event", "event": "sessions.changed", "payload": "oops"})
    assert p.snapshot() == ()


@pytest.mark.asyncio
async def test_projector_ignores_payload_missing_session_key() -> None:
    p = SessionStateProjector()
    frame = {
        "type": "event",
        "event": "sessions.changed",
        "payload": {"phase": "message", "ts": 1},
        "seq": 1,
    }
    await p(frame)
    assert p.snapshot() == ()


@pytest.mark.asyncio
async def test_projector_handles_event_without_token_counts() -> None:
    """Some sessions.changed phases (e.g. session-created) may omit
    token counters — the projector must still record the row with the
    fields it does have."""
    p = SessionStateProjector()
    await p(
        _make_event(
            phase="created",
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        )
    )
    states = p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66")
    assert len(states) == 1
    assert states[0].input_tokens is None
    assert states[0].output_tokens is None
    assert states[0].total_tokens is None
    assert states[0].last_phase == "created"


@pytest.mark.asyncio
async def test_projector_snapshot_returns_immutable_tuple() -> None:
    """``snapshot()`` is the read API for the rest of MC; returning a
    tuple means callers cannot accidentally corrupt the projector's
    internal state and the dict-keying scheme stays an implementation
    detail."""
    p = SessionStateProjector()
    await p(_make_event())
    snap = p.snapshot()
    assert isinstance(snap, tuple)
    assert len(snap) == 1
    # Subsequent projections must not mutate previously-returned snapshots.
    await p(_make_event(session_key="agent:mc-other-1234:main"))
    assert len(snap) == 1
    assert len(p.snapshot()) == 2


# ---------------------------------------------------------------------------
# Slice 6: ACP-completion projection — parent_session_key, last_status,
# last_lifecycle_reason captured from sessions.changed lifecycle events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projector_records_parent_session_key_for_acp_child() -> None:
    """When the gateway broadcasts a sessions.changed event for an ACP
    child, ``parentSessionKey`` is set in the inner payload (per
    ``server-session-events.ts`` createLifecycleEventBroadcastHandler).
    The projector must capture it so MC can answer "what are this
    agent's spawned children?" via SQL."""
    p = SessionStateProjector()
    await p(
        _make_event(
            session_key="agent:mc-child-1234:spawn",
            parent_session_key="agent:mc-parent-5678:main",
        )
    )
    states = p.get("mc-child-1234")
    assert len(states) == 1
    assert states[0].parent_session_key == "agent:mc-parent-5678:main"


@pytest.mark.asyncio
async def test_projector_records_status_and_reason_for_acp_completion() -> None:
    """ACP child completion lands as ``reason="subagent-status"`` (the
    gateway's only broadcast on child status mutations, verified at
    subagent-registry-lifecycle.ts:606) carrying the terminal status
    in the same payload. MC derives "this ACP child finished" by
    matching the terminal ``status`` (``done``/``failed``/``timed_out``)
    rather than by ``reason`` — the ``endedReason`` enum
    (``completed``/``expiry``/``spawn-failed``/``retry-limit``) stays
    local to the gateway and never reaches subscribers."""
    p = SessionStateProjector()
    await p(
        _make_event(
            session_key="agent:mc-child-1234:spawn",
            parent_session_key="agent:mc-parent-5678:main",
            phase="end",
            status="done",
            reason="subagent-status",
        )
    )
    states = p.get("mc-child-1234")
    assert len(states) == 1
    assert states[0].last_status == "done"
    assert states[0].last_lifecycle_reason == "subagent-status"


@pytest.mark.asyncio
async def test_projector_records_actually_broadcast_lifecycle_reasons() -> None:
    """Verified 5.3 broadcast vocabulary is 12 strings from 3 source
    files (every ``emitSessionLifecycleEvent``/``emitSessionsChanged``
    call site enumerated 2026-05-04 against gateway source on .60):

    * ``sessions.ts`` (10): send, steer, create, patch, new, reset,
      abort, delete, checkpoint-branch, checkpoint-restore, compact.
    * ``subagent-spawn.ts`` (1): create (dedup with sessions.ts).
    * ``subagent-registry-lifecycle.ts`` (1): subagent-status.

    Earlier audits incorrectly listed ``"deleted"`` (past tense) as
    broadcast from ``session-reset-service.ts``; verified that file
    has zero broadcast call sites. Only ``"delete"`` (no ``d``) hits
    the wire, from sessions.delete RPC. The internal ``endedReason``
    enum (``completed``/``expiry``/``spawn-failed``/``retry-limit``)
    stays local to the gateway and never reaches subscribers.

    Pin the actually-observed vocabulary so the round-trip contract
    is clear. Use a 3-segment session key per spawn so the slice-6
    cardinality guard (``acp:`` 4-segment drop) doesn't reject the
    test fixture.
    """
    broadcast_reasons = (
        "send",
        "steer",
        "create",
        "patch",
        "new",
        "reset",
        "abort",
        "delete",
        "checkpoint-branch",
        "checkpoint-restore",
        "compact",
        "subagent-status",
    )
    for reason in broadcast_reasons:
        p = SessionStateProjector()
        await p(
            _make_event(
                session_key=f"agent:mc-child-{reason.replace('-', '_')}:main",
                parent_session_key="agent:mc-parent-5678:main",
                reason=reason,
            )
        )
        states = p.get(f"mc-child-{reason.replace('-', '_')}")
        assert len(states) == 1
        assert states[0].last_lifecycle_reason == reason


@pytest.mark.asyncio
async def test_projector_lifecycle_fields_default_to_none_when_absent() -> None:
    """Most ``sessions.changed`` events carry only ``phase``, not the
    lifecycle-specific ``status``/``reason``/``parentSessionKey`` set.
    The projector must still record the row with ``None`` defaults so
    legacy events don't crash and slice-4 projections stay intact."""
    p = SessionStateProjector()
    await p(_make_event())  # no parent/status/reason kwargs
    states = p.get("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66")
    assert len(states) == 1
    assert states[0].parent_session_key is None
    assert states[0].last_status is None
    assert states[0].last_lifecycle_reason is None


@pytest.mark.asyncio
async def test_projector_captures_4_segment_heartbeat_sub_session() -> None:
    """Slice-3 parser dropped 4-segment keys (``agent:lead-X:main:heartbeat``).
    Slice 6 widens parse_session_key to accept them as labelled rows.
    Verify the projector now records them under the joined label."""
    p = SessionStateProjector()
    await p(
        _make_event(
            session_key="agent:lead-05002170-201b-4c66-bae1-26c0c833f206:main:heartbeat",
            phase="end",
            status="done",
        )
    )
    states = p.get("lead-05002170-201b-4c66-bae1-26c0c833f206")
    assert len(states) == 1
    assert states[0].session_label == "main:heartbeat"
    assert states[0].last_status == "done"


# ---------------------------------------------------------------------------
# Codex 2026-05-04 finding: lifecycle sessions.changed events emit fields at
# the TOP of the inner payload (no nested ``session`` object). Slice 4 read
# from ``payload.session.X`` only, silently dropping data on every lifecycle
# event and overwriting previously-correct values with None.
# ---------------------------------------------------------------------------


def _make_lifecycle_event(
    *,
    session_key: str = "agent:mc-aaaaaaaa-1111-2222-3333-444444444444:main",
    ts: int = 1_777_900_000_000,
    reason: str = "subagent-status",
    status: str = "done",
    input_tokens: int = 1234,
    output_tokens: int = 567,
    total_tokens: int = 1801,
    channel: str = "webchat",
    aborted_last_run: bool = False,
    session_id: str = "abc-def",
) -> dict:
    """Build a lifecycle-shape sessions.changed frame: fields at the TOP of
    the inner payload, NO nested ``session`` object. Mirrors what
    ``createLifecycleEventBroadcastHandler`` (server-session-events.ts:152+)
    actually broadcasts — verified against live 5.3 capture."""
    return {
        "type": "event",
        "event": "sessions.changed",
        "payload": {
            "sessionKey": session_key,
            "ts": ts,
            "reason": reason,
            "status": status,
            "sessionId": session_id,
            "channel": channel,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
            "abortedLastRun": aborted_last_run,
        },
        "seq": 1,
    }


@pytest.mark.asyncio
async def test_projector_reads_top_level_fields_on_lifecycle_event() -> None:
    """SHIPPED BUG REGRESSION: lifecycle events have NO nested ``session``
    object — slice-4 reads ``payload.session.<field>`` and got None for
    every token/channel/aborted/sessionId field, then wrote None to the
    DB, clobbering valid data captured from prior message events."""
    p = SessionStateProjector()
    await p(_make_lifecycle_event())
    states = p.get("mc-aaaaaaaa-1111-2222-3333-444444444444")
    assert len(states) == 1
    s = states[0]
    assert s.input_tokens == 1234
    assert s.output_tokens == 567
    assert s.total_tokens == 1801
    assert s.channel == "webchat"
    assert s.session_id == "abc-def"
    assert s.aborted_last_run is False
    assert s.last_lifecycle_reason == "subagent-status"
    assert s.last_status == "done"


@pytest.mark.asyncio
async def test_projector_prefers_top_level_when_both_locations_present() -> None:
    """Message-phase events carry the same fields BOTH at top-level AND
    nested under ``session``. When both are present, prefer top-level —
    that's the authoritative gateway-side field; the nested mirror is a
    legacy artefact from older event shapes. Pin top-wins so future
    drift between the two doesn't leave the projector reading stale."""
    frame = {
        "type": "event",
        "event": "sessions.changed",
        "payload": {
            "sessionKey": "agent:mc-bbbbbbbb-1111-2222-3333-444444444444:main",
            "ts": 1_777_900_000_000,
            "phase": "message",
            "inputTokens": 999,
            "totalTokens": 1500,
            "channel": "top-channel",
            "abortedLastRun": True,
            "sessionId": "top-session-id",
            "session": {
                "inputTokens": 0,
                "totalTokens": 0,
                "channel": "nested-channel",
                "abortedLastRun": False,
                "sessionId": "nested-session-id",
            },
        },
        "seq": 1,
    }
    p = SessionStateProjector()
    await p(frame)
    states = p.get("mc-bbbbbbbb-1111-2222-3333-444444444444")
    assert len(states) == 1
    s = states[0]
    assert s.input_tokens == 999
    assert s.total_tokens == 1500
    assert s.channel == "top-channel"
    assert s.session_id == "top-session-id"
    assert s.aborted_last_run is True


@pytest.mark.asyncio
async def test_projector_falls_back_to_nested_when_top_level_absent() -> None:
    """Backwards-compat: older 4.x events put fields ONLY under nested
    ``session``. After fixing the bug, the projector should still
    extract them when top-level is missing."""
    frame = {
        "type": "event",
        "event": "sessions.changed",
        "payload": {
            "sessionKey": "agent:mc-cccccccc-1111-2222-3333-444444444444:main",
            "ts": 1_777_900_000_000,
            "phase": "message",
            "session": {
                "inputTokens": 42,
                "outputTokens": 13,
                "totalTokens": 55,
                "channel": "nested-only",
                "abortedLastRun": True,
                "sessionId": "nested-only-id",
            },
        },
        "seq": 1,
    }
    p = SessionStateProjector()
    await p(frame)
    states = p.get("mc-cccccccc-1111-2222-3333-444444444444")
    assert len(states) == 1
    s = states[0]
    assert s.input_tokens == 42
    assert s.output_tokens == 13
    assert s.total_tokens == 55
    assert s.channel == "nested-only"
    assert s.session_id == "nested-only-id"
    assert s.aborted_last_run is True
