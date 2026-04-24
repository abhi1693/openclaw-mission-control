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
# Leading mentions (``@Supervisor @QA-E2E @lead Acknowledged.``) count as
# ack-head — Phase VII echo-gate relies on this to catch the Architect
# half of the 2026-04-17 echo storm where the pre-extension regex missed
# messages whose first word was a mention rather than the ack verb.
ACK_HEAD_RE = re.compile(
    r"(?m)^\s*(?:@\S+\s+)*"
    r"(acknowledged|received|confirmed|understood|noted|aligned|ack(?:nowledged)?)\b",
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

# Phase VII: state-reassurance phrases that the 2026-04-17 Architect↔
# Supervisor echo storm used to paraphrase "nothing has changed, we
# agree" without carrying evidence. Distinct from ACK_PHRASE_RE: those
# are explicit "no change" statements; these are reassurance cliches
# that restate the counterpart's position without adding delta. Both
# feed into ECHO_SHAPE.
#
# Kept narrow — each phrase is drawn from the actual storm corpus, not
# speculative patterns, to avoid false-firing on legitimate alignment
# comments that happen to include the word "matches".
ECHO_PHRASE_RE = re.compile(
    r"\b("
    r"on that exact truth|"
    r"on that same truth|"
    r"matches my (?:current )?verdict|"
    r"matches my (?:current )?read|"
    r"lead is holding (?:the |that )?same|"
    r"keep (?:the )?(?:lane|gate) fail[- ]closed|"
    r"stays? out of (?:lane|qa)|"
    r"no net[- ]new (?:lead )?action|"
    r"no (?:net[- ]new )?(?:lead )?evidence"
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

# Phase VII refinement (2026-04-24): extract the *actual* evidence
# tokens from a message so the classifier can distinguish "new
# evidence" from "same evidence as last time." The 2026-04-23 echo
# storm bypass used hourly "Sweep response: http://.64:3000/docs →
# 404" posts — the URL + HTTP code tripped ``has_negative_evidence``
# every time even though neither had changed since the prior same-
# author comment. These extractors produce a canonical set so the
# caller can compute ``evidence(new) − evidence(prior) = ∅`` and
# re-classify as echo despite apparent negative evidence.
_EVIDENCE_URL_RE = re.compile(r"https?://\S+")
_EVIDENCE_SHA_RE = re.compile(r"\b[a-f0-9]{7,40}\b")
_EVIDENCE_HTTP_CODE_RE = re.compile(r"\bHTTP\s*\d{3}\b", re.IGNORECASE)
_EVIDENCE_TEST_TOKEN_RE = re.compile(
    r"\b(PASS|FAIL|running tests?|lighthouse|playwright|vitest|build PASS)\b"
)
_EVIDENCE_FILE_RE = re.compile(
    r"\b\w+\.(py|ts|tsx|jsx|js|json5?|md|sql|yml|yaml|sh|toml|lock)\b",
    re.IGNORECASE,
)


def evidence_markers(message: str) -> frozenset[str]:
    """Canonical set of evidence tokens in ``message``.

    Normalises URL trailing punctuation (``http://x)`` → ``http://x``)
    and lowercases HTTP codes so "HTTP 404" and "http 404" compare
    equal. SHAs are already lowercase-hex per their regex.
    """

    markers: set[str] = set()
    for url in _EVIDENCE_URL_RE.findall(message):
        markers.add(url.rstrip(".,;:)]}`\"'"))
    markers.update(_EVIDENCE_SHA_RE.findall(message))
    markers.update(code.upper() for code in _EVIDENCE_HTTP_CODE_RE.findall(message))
    markers.update(_EVIDENCE_TEST_TOKEN_RE.findall(message))
    markers.update(f".{ext}" for ext in _EVIDENCE_FILE_RE.findall(message))
    return frozenset(markers)


def has_new_negative_evidence(message: str, prior: str | None) -> bool:
    """Return True when ``message`` carries at least one evidence
    marker that isn't present in ``prior``.

    ``prior=None`` means no comparable baseline — default to True so
    a first-ever message with evidence is never treated as echo. An
    empty-marker message (no URLs, no SHAs, no HTTP codes) trivially
    has no new markers — returns False, lets the echo classifier
    decide on shape alone.
    """

    current = evidence_markers(message)
    if not current:
        return False
    if prior is None:
        return True
    return bool(current - evidence_markers(prior))

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
