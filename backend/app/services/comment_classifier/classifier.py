"""The ``classify`` entry point and ``ClassifierFlag`` enum.

The classifier is deliberately pure: no DB access, no logging side
effects. Callers supply the current message plus optional context (prior
comment + timestamp, packet type) and receive a list of structured flags.
Persistence, notification, and filter-mode behaviour live in the callers.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from app.services.comment_classifier.patterns import (
    ACK_HEAD_RE,
    ACK_MAX_WORDS,
    ACK_PHRASE_RE,
    LAX_MAX_WORDS,
    LAX_PACKET_TYPES,
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    NEAR_DUPLICATE_WINDOW_SECONDS,
    has_negative_evidence,
    has_routing_verb,
    jaccard,
    normalize_for_jaccard,
    word_count,
)


class ClassifierFlag(StrEnum):
    """Structured flags returned by ``classify``.

    Kept as a ``StrEnum`` so serialised values in ``ActivityEvent.
    classifier_flags`` (future Phase 0 column) stay readable in the DB
    without a separate reverse-mapping.
    """

    ACK_ONLY = "ack_only"
    NEAR_DUPLICATE = "near_duplicate"


def _has_ack_shape(message: str) -> bool:
    return bool(ACK_HEAD_RE.search(message) or ACK_PHRASE_RE.search(message))


def _is_ack_only(message: str, *, packet_type: str | None) -> bool:
    """Decide whether a message is an ack-only comment.

    Strict packet types (``frontend_ui``, ``backend_api``, ``infra_ops``,
    ``mixed``) and unspecified packet types expect evidence on any
    substantive comment; ack-shaped messages without evidence are noise.

    Lax packet types (``review_only``, ``content_copy``, ``other``)
    legitimately produce short acks like "looks good to me"; only flag
    when the message is short AND carries no routing verb.
    """

    if not _has_ack_shape(message):
        return False
    if has_negative_evidence(message):
        return False
    if word_count(message) > ACK_MAX_WORDS:
        return False
    if has_routing_verb(message):
        return False

    if packet_type in LAX_PACKET_TYPES:
        return word_count(message) <= LAX_MAX_WORDS
    # Strict, unset, or unrecognized packet types all flag. Unknown is
    # treated as strict: safer to over-flag a legit comment (operator
    # toggles include_flagged=true) than silently under-flag theater.
    return True


def _is_near_duplicate(
    message: str,
    *,
    prior: str | None,
    gap_seconds: float | None,
) -> bool:
    """Compare ``message`` to the same author's previous same-task comment.

    The caller is responsible for fetching the right ``prior`` (same
    agent + same task + most recent within the window). Time-window and
    similarity gates are applied here.
    """

    if prior is None or gap_seconds is None:
        return False
    if gap_seconds < 0 or gap_seconds > NEAR_DUPLICATE_WINDOW_SECONDS:
        return False
    sim = jaccard(normalize_for_jaccard(prior), normalize_for_jaccard(message))
    return sim >= NEAR_DUPLICATE_JACCARD_THRESHOLD


def classify(
    message: str,
    *,
    packet_type: str | None = None,
    prior_comment: str | None = None,
    prior_comment_created_at: datetime | None = None,
    now: datetime | None = None,
) -> list[ClassifierFlag]:
    """Classify a single task comment.

    Args:
        message: the current comment's raw message body.
        packet_type: ``task.review_packet_type``, one of the prod
            ``ReviewPacketType`` literals, or None if unset.
        prior_comment: the most recent prior comment on the same task by
            the same author. None if none within the dedup window.
        prior_comment_created_at: when ``prior_comment`` was posted.
            Required iff ``prior_comment`` is provided.
        now: override for test determinism. Defaults to real time.

    Returns:
        Ordered list of ``ClassifierFlag`` values. Empty when the
        comment has no matching rule.
    """

    flags: list[ClassifierFlag] = []

    if _is_ack_only(message, packet_type=packet_type):
        flags.append(ClassifierFlag.ACK_ONLY)

    gap: float | None = None
    if prior_comment is not None and prior_comment_created_at is not None:
        reference = now or datetime.now(prior_comment_created_at.tzinfo)
        gap = (reference - prior_comment_created_at).total_seconds()
    if _is_near_duplicate(message, prior=prior_comment, gap_seconds=gap):
        flags.append(ClassifierFlag.NEAR_DUPLICATE)

    return flags
