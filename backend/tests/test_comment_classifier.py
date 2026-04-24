# ruff: noqa: INP001
"""Unit tests for the shared comment classifier library.

Covers amendment sections A.2 (shared classifier library), 2 (healthy-
corpus calibration gate design), and 3 (packet-type severity modifier)
from ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.comment_classifier import ClassifierFlag, classify


# --- Rule A: ack-only detection ------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Acknowledged. Holding exactly there. No status change. @lead",
        "Received — holding fail-closed, no approval path.",
        "Confirmed. Stays unchanged.",
        "Noted. Silence is correct.",
    ],
)
def test_ack_only_flagged_on_strict_packet(message: str) -> None:
    """Prototype ack-theater messages must flag under strict packet types."""

    flags = classify(message, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY in flags


@pytest.mark.parametrize(
    "packet_type",
    ["frontend_ui", "backend_api", "infra_ops", "mixed", None],
)
def test_ack_only_flagged_on_all_strict_packet_types(packet_type: str | None) -> None:
    """Strict packet types + unspecified all apply the strict rule."""

    msg = "Acknowledged. Holding there."
    flags = classify(msg, packet_type=packet_type)
    assert ClassifierFlag.ACK_ONLY in flags


def test_ack_only_exempt_on_lax_packet_when_short_and_no_routing() -> None:
    """Lax packet type + short message + no routing = legitimate reviewer ack.

    Still flagged as ack_only because the message IS ack-shaped; lax
    severity governs whether callers HIDE it, not whether the classifier
    records it. Actually the spec says lax flag only when short AND no
    routing; test reflects that.
    """

    msg = "Confirmed."
    # Short (1 word), no routing, lax packet — flagged.
    flags = classify(msg, packet_type="review_only")
    assert ClassifierFlag.ACK_ONLY in flags


def test_ack_only_not_flagged_on_lax_packet_when_long() -> None:
    """Lax packet type + more than ``LAX_MAX_WORDS`` words = substantive review."""

    msg = " ".join(["Confirmed"] * 20) + ". Review comment below."
    flags = classify(msg, packet_type="review_only")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_on_lax_packet_with_routing_verb() -> None:
    """Short lax-packet ack with routing is legit hand-off, not theater."""

    msg = "Acknowledged. Reassigning to Architect for review."
    flags = classify(msg, packet_type="review_only")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_carries_code_fence() -> None:
    msg = "Acknowledged. Here is the evidence:\n```\ncurl http://foo\n```"
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_cites_a_file() -> None:
    msg = "Acknowledged. Fixed in src/pages/DocsPage.jsx:36."
    flags = classify(msg, packet_type="backend_api")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_cites_a_commit_sha() -> None:
    msg = "Acknowledged. Landed as 6e07c7df."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_carries_test_output() -> None:
    msg = "Acknowledged. Full suite PASS; 25/25 green."
    flags = classify(msg, packet_type="backend_api")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_is_very_long() -> None:
    """A 300+ word message is presumed substantive even if ack-shaped."""

    msg = "Acknowledged. " + ("word " * 305)
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_when_message_has_routing_verb() -> None:
    msg = "Acknowledged. Reassigning to Architect."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_ack_only_not_flagged_on_substantive_opening() -> None:
    """Real content that doesn't match the ack regex is not flagged."""

    msg = "Filed PR #247 against feature/phase-0-workflow-invariants."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


# --- Rule B: near-duplicate detection ------------------------------------


def test_near_duplicate_flagged_on_exact_repeat() -> None:
    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(minutes=2)
    msg = "Acknowledged. No status change. @lead"
    flags = classify(
        msg,
        packet_type="frontend_ui",
        prior_comment=msg,
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.NEAR_DUPLICATE in flags


def test_near_duplicate_flagged_above_threshold() -> None:
    """>= 0.90 jaccard within window counts as duplicate."""

    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(seconds=60)
    prior = "Acknowledged. Track E remains fail-closed. No status change."
    current = "Acknowledged. Track E remains fail-closed. No status change yet."
    flags = classify(
        current,
        packet_type="frontend_ui",
        prior_comment=prior,
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.NEAR_DUPLICATE in flags


def test_near_duplicate_not_flagged_under_threshold() -> None:
    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(seconds=60)
    flags = classify(
        "Completely different message here with new words",
        packet_type="frontend_ui",
        prior_comment="Original prior comment unrelated",
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.NEAR_DUPLICATE not in flags


def test_near_duplicate_not_flagged_outside_window() -> None:
    """Same content after 6 minutes is not a duplicate."""

    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(minutes=6)
    msg = "Acknowledged. Holding there."
    flags = classify(
        msg,
        packet_type="frontend_ui",
        prior_comment=msg,
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.NEAR_DUPLICATE not in flags


def test_near_duplicate_requires_prior_context() -> None:
    """Missing prior_comment -> never flagged as duplicate."""

    flags = classify("any message", packet_type="frontend_ui")
    assert ClassifierFlag.NEAR_DUPLICATE not in flags


def test_near_duplicate_rejects_mention_only_differences() -> None:
    """Adding only a new @mention keeps jaccard high; should still flag.

    Normalization strips mentions before comparing.
    """

    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(seconds=30)
    flags = classify(
        "Acknowledged. Holding there. @architect",
        packet_type="frontend_ui",
        prior_comment="Acknowledged. Holding there. @lead",
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.NEAR_DUPLICATE in flags


# --- Multi-flag + API contract -------------------------------------------


def test_both_flags_can_coexist() -> None:
    """An ack-only duplicate earns both flags."""

    prior_time = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    now = prior_time + timedelta(seconds=30)
    msg = "Acknowledged. Holding exactly there. @lead"
    flags = classify(
        msg,
        packet_type="frontend_ui",
        prior_comment=msg,
        prior_comment_created_at=prior_time,
        now=now,
    )
    assert ClassifierFlag.ACK_ONLY in flags
    assert ClassifierFlag.NEAR_DUPLICATE in flags


def test_classify_returns_empty_for_clean_message() -> None:
    msg = "Filed PR, ran tests, all green. Ready for review."
    flags = classify(msg, packet_type="frontend_ui")
    assert flags == []


def test_classifier_flag_values_are_stable_strings() -> None:
    """StrEnum values are the DB-serialised form; must not change casually."""

    assert str(ClassifierFlag.ACK_ONLY) == "ack_only"
    assert str(ClassifierFlag.NEAR_DUPLICATE) == "near_duplicate"


# --- Codex review fixes: FAIL signal, bare routing, tz mix, md preamble ---


@pytest.mark.parametrize(
    "message",
    [
        "Acknowledged. FAIL: 1 test failing.",
        "Acknowledged. FAIL: see log.",
        "Acknowledged. FAIL - see stack trace",
        "Acknowledged. The pytest FAIL was on line 40",
    ],
)
def test_ack_only_not_flagged_when_message_contains_FAIL(message: str) -> None:
    """FAIL is a test-failure signal — counts as negative evidence.

    Codex HIGH review: the prior ``FAIL\\s*:`` regex had a broken ``\\b``
    anchor after the colon, so ``FAIL: 1 test failing`` slipped through
    and got flagged as pure ack.
    """

    flags = classify(message, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


@pytest.mark.parametrize(
    "message",
    [
        "Acknowledged. Reassigning.",
        "Acknowledged. Routing through Architect.",
        "Acknowledged. Sending the patch.",
        "Acknowledged. Delegating.",
        "Acknowledged. Escalating to OP-1.",
    ],
)
def test_ack_only_not_flagged_on_bare_routing_verbs(message: str) -> None:
    """Bare routing verbs exempt the comment from ack-only theater.

    Codex MEDIUM review: the narrow ``verb + to|back|this|it|up|over``
    regex missed legitimate routing like ``Routing through Architect``
    or ``Sending the patch``.
    """

    flags = classify(message, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


def test_classify_handles_mixed_tz_awareness_without_crashing() -> None:
    """Codex MEDIUM: prod stores naive UTC; a caller-supplied aware
    ``now`` with a naive DB prior must not raise TypeError."""

    from datetime import timezone as _tz

    naive_prior_time = datetime(2026, 4, 17, 12, 0, 0)  # no tzinfo
    aware_now = datetime(2026, 4, 17, 12, 0, 30, tzinfo=_tz.utc)
    msg = "Acknowledged. No status change. @lead"
    flags = classify(
        msg,
        packet_type="frontend_ui",
        prior_comment=msg,
        prior_comment_created_at=naive_prior_time,
        now=aware_now,
    )
    # Specifically: no TypeError raised. Duplicate detection still works
    # because both sides are normalized to naive before subtraction.
    assert ClassifierFlag.NEAR_DUPLICATE in flags


def test_ack_only_flagged_after_markdown_preamble() -> None:
    """Codex LOW: absolute-start anchor missed ack tokens that follow a
    markdown header or blockquote. MULTILINE fixes the miss."""

    msg = "# Update\nAcknowledged. No status change."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY in flags


def test_ack_only_not_flagged_when_message_cites_json5_file() -> None:
    """Codex LOW: the extension allowlist missed ``json5``."""

    msg = "Acknowledged. Fixed in config.json5."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ACK_ONLY not in flags


# ---------------------------------------------------------------
# Phase VII refinement (2026-04-24): prior-relative evidence —
# re-quoting the same URL + HTTP code as the prior same-author
# comment no longer counts as "new evidence" that defeats the
# echo-shape gate. Closes the bypass the 2026-04-23 storm used.
# ---------------------------------------------------------------


def test_echo_shape_fires_when_evidence_matches_prior_verbatim() -> None:
    """2026-04-23 storm pattern: hourly re-post citing the same URL +
    same HTTP code as the previous comment. Pre-refinement this passed
    the classifier because URL + ``HTTP 404`` tripped
    ``has_negative_evidence``. Now the prior-relative check kicks in:
    delta is empty → echo-shape fires."""

    prior = (
        "Confirmed. D.3 stays fail-closed. http://192.168.2.64:3000/docs "
        "is still HTTP 404."
    )
    new = (
        "Confirmed. D.3 stays fail-closed. No net-new lead evidence. "
        "http://192.168.2.64:3000/docs still HTTP 404."
    )
    flags = classify(new, packet_type="frontend_ui", prior_comment=prior)
    assert ClassifierFlag.ECHO_SHAPE in flags


def test_echo_shape_does_not_fire_on_new_http_code_vs_prior() -> None:
    """Legit progress: same URL, but HTTP code changed (404 → 200).
    The HTTP-code delta is new evidence — echo-shape must stay silent
    so the classifier doesn't punish real unblocking updates."""

    prior = (
        "Confirmed. http://192.168.2.64:3000/docs is HTTP 404 — still "
        "not the shipped DocsPage."
    )
    new = (
        "Confirmed. http://192.168.2.64:3000/docs now returns HTTP 200 "
        "— deploy landed."
    )
    flags = classify(new, packet_type="frontend_ui", prior_comment=prior)
    assert ClassifierFlag.ECHO_SHAPE not in flags


def test_echo_shape_does_not_fire_when_new_sha_added() -> None:
    """Evidence delta = new SHA reference. Must not suppress."""

    prior = "Confirmed. Retested http://192.168.2.60:3000/app. Still HTTP 404."
    new = (
        "Confirmed. Retested http://192.168.2.60:3000/app at commit "
        "abc1234 — still HTTP 404."
    )
    flags = classify(new, packet_type="frontend_ui", prior_comment=prior)
    assert ClassifierFlag.ECHO_SHAPE not in flags


def test_echo_shape_fires_when_no_prior_and_only_bare_phrase() -> None:
    """Control: without a prior, messages with NO evidence markers but
    echo-shape language still fire. (This was the pre-refinement
    behaviour — refinement must not break it.)"""

    msg = "Confirmed. Lead is holding the same D.1 truth."
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ECHO_SHAPE in flags


def test_first_message_with_evidence_not_flagged_even_with_echo_shape() -> None:
    """Prior=None means no comparison baseline. Any evidence marker
    stays disqualifying — a FIRST comment carrying a URL + HTTP code
    is by definition not an echo."""

    msg = (
        "Acknowledged. Retested http://192.168.2.60:3000/app. Returned "
        "HTTP 404. Will re-check next sweep."
    )
    flags = classify(msg, packet_type="frontend_ui")
    assert ClassifierFlag.ECHO_SHAPE not in flags
    assert ClassifierFlag.ACK_ONLY not in flags
