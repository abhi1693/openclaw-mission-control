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
