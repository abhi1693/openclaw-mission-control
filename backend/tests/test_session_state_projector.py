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
    assert parse_session_key(
        "agent:mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66:main"
    ) == ("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66", "main")


def test_parse_session_key_supports_lead_and_gateway_prefixes() -> None:
    assert parse_session_key(
        "agent:lead-aaaa1234-1111-2222-3333-444444444444:main"
    ) == ("lead-aaaa1234-1111-2222-3333-444444444444", "main")
    assert parse_session_key(
        "agent:mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e:main"
    ) == ("mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e", "main")


def test_parse_session_key_supports_non_main_label() -> None:
    """Some sessions use labels other than ``main`` (e.g. side-channel
    bots). The parser must not hard-code the label."""
    assert parse_session_key(
        "agent:mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66:debug"
    ) == ("mc-dd1abee5-97f0-4aaa-8d34-ecac1f7ddf66", "debug")


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
