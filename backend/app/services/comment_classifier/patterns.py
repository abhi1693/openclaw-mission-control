"""Regex patterns and packet-type taxonomy for the comment classifier.

Kept in its own module so the calibration script at
``scripts/calibrate_comment_classifier.py`` can import patterns without
pulling in the full classifier dependency tree, and so rule tuning is a
focused diff against a single file.

Helpers are package-public (no leading underscore) because they are
imported by the sibling ``classifier`` module. The module as a whole is
an implementation detail of ``app.services.comment_classifier``.
"""

from __future__ import annotations

import re
from typing import get_args

from app.schemas.tasks import (
    REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET,
    ReviewPacketType,
)
from app.services.mentions import MENTION_PATTERN

# --- Rule A: ack-only detection ------------------------------------------

# MULTILINE so markdown preambles ("# Update\nAcknowledged.") still match.
ACK_HEAD_RE = re.compile(
    r"(?m)^\s*(acknowledged|received|confirmed|understood|noted|ack(?:nowledged)?)\b",
    re.IGNORECASE,
)

ACK_PHRASE_RE = re.compile(
    r"\b("
    r"no status change|no change|"
    r"holding (?:unchanged|exactly|there)|hold (?:unchanged|exactly|there)|"
    r"fail[- ]closed|stays? unchanged|"
    r"no approval path|no advancement|"
    r"silence is correct|"
    r"remains? (?:unchanged|fail[- ]closed)"
    r")\b",
    re.IGNORECASE,
)

_NEG_EVIDENCE_PARTS: tuple[re.Pattern[str], ...] = (
    # fenced or inline code
    re.compile(r"```", re.MULTILINE),
    # file reference with extension
    re.compile(
        r"\b\w+\.(py|ts|tsx|jsx|js|json5?|md|sql|yml|yaml|sh|toml|lock)\b",
        re.IGNORECASE,
    ),
    # URL
    re.compile(r"https?://"),
    # git SHA shape — word-bounded to avoid long UUID false hits
    re.compile(r"\b[a-f0-9]{7,40}\b"),
    # test / build / HTTP signals. FAIL is matched standalone (the earlier
    # `FAIL\s*:\b` form was broken — `\b` after `:` needed a following
    # word char, which `FAIL: 1 test failing` never provides).
    re.compile(
        r"\b(PASS|FAIL|running tests?|lighthouse|playwright|vitest|"
        r"build PASS|HTTP \d{3})\b"
    ),
)

# Routing/hand-off verbs. The verb alone is sufficient signal — requiring
# a specific follower (to|back|this|it|up|over) missed bare "reassigning"
# and complements like "sending the patch" / "routing through Architect".
# In shadow-flagging mode a false negative (incidental "sending" word
# treated as routing) is bounded; a false positive (legit hand-off
# misclassified as ack-theater) is more disruptive.
ROUTING_VERB_RE = re.compile(
    r"\b(reassign(?:ing|ed|s)?|routing|bouncing|sending|handing|"
    r"forwarding|delegating|escalating)\b",
    re.IGNORECASE,
)

# Above this word count, ack-shaped messages are presumed to carry real
# substance even if they also happen to contain acknowledgment phrasing.
ACK_MAX_WORDS = 300

# --- Packet-type severity modulation -------------------------------------
#
# Shares taxonomy with the prod delivery-contract code so a new
# ``ReviewPacketType`` addition updates both call sites atomically.

STRICT_PACKET_TYPES = REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET
LAX_PACKET_TYPES: frozenset[str] = frozenset(get_args(ReviewPacketType)) - STRICT_PACKET_TYPES
LAX_MAX_WORDS = 15

# --- Rule B: near-duplicate detection ------------------------------------

NEAR_DUPLICATE_WINDOW_SECONDS = 300
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.90

_STRIP_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_STRIP_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_STRIP_URL_RE = re.compile(r"https?://\S+")
_PUNCT_TO_SPACE_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def has_negative_evidence(message: str) -> bool:
    return any(pattern.search(message) for pattern in _NEG_EVIDENCE_PARTS)


def has_routing_verb(message: str) -> bool:
    return ROUTING_VERB_RE.search(message) is not None


def word_count(message: str) -> int:
    return len(message.split())


def normalize_for_jaccard(message: str) -> str:
    s = _STRIP_CODE_FENCE_RE.sub("", message)
    s = _STRIP_INLINE_CODE_RE.sub("", s)
    s = MENTION_PATTERN.sub("", s)
    s = _STRIP_URL_RE.sub("", s)
    s = _PUNCT_TO_SPACE_RE.sub(" ", s).lower()
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union)
