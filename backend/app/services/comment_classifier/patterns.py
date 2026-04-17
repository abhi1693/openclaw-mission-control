"""Regex patterns and packet-type taxonomy for the comment classifier.

Kept in their own module so the calibration script at
``scripts/calibrate_comment_classifier.py`` can import them without
pulling in the full classifier dependency tree, and so future rule
tuning is a focused diff against a single file.
"""

from __future__ import annotations

import re

# --- Rule A: ack-only detection ------------------------------------------

# Anchored at message start (first ~40 chars). Matches opening receipts.
ACK_HEAD_RE = re.compile(
    r"^\s*(acknowledged|received|confirmed|understood|noted|ack(?:nowledged)?)\b",
    re.IGNORECASE,
)

# Phrase anywhere in the body. Matches the "holding fail-closed, no change,
# silence is correct" language that dominates Supervisor/QA acknowledgment
# theater on the Dev Squad incident corpus.
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

# Negative evidence: any one of these disqualifies an otherwise-ack-shaped
# comment. Presence signals the author added real information.
_NEG_EVIDENCE_PARTS: tuple[re.Pattern[str], ...] = (
    # fenced or inline code
    re.compile(r"```", re.MULTILINE),
    # file reference with extension
    re.compile(
        r"\b\w+\.(py|ts|tsx|jsx|js|json|md|sql|yml|yaml|sh|toml|lock)\b",
        re.IGNORECASE,
    ),
    # URL
    re.compile(r"https?://"),
    # git SHA shape (anchored at word boundary to avoid false hits on long
    # uuids that happen to start with hex chars — uuid includes hyphens)
    re.compile(r"\b[a-f0-9]{7,40}\b"),
    # test / build / HTTP signals
    re.compile(
        r"\b(PASS|FAIL\s*:|running tests?|lighthouse|playwright|vitest|"
        r"build PASS|HTTP \d{3})\b"
    ),
)

# English routing verbs: even short messages are legitimate when they
# hand work off to a different role.
ROUTING_VERB_RE = re.compile(
    r"\b(reassign(?:ing)?|routing|bouncing|sending|handing|forwarding|"
    r"delegating|escalating)\s+(?:to|back|this|it|up|over)\b",
    re.IGNORECASE,
)

# Above this word count, ack-shaped messages are presumed to carry real
# substance even if they also happen to contain acknowledgment phrasing.
ACK_MAX_WORDS = 300

# --- Packet-type severity modulation -------------------------------------
#
# Taxonomy from prod ``backend/app/schemas/tasks.py`` (ReviewPacketType).
# Strict types expect evidence on every substantive comment; short acks
# are noise. Lax types (reviews, copy) legitimately produce short acks;
# the classifier only flags them when the message is both short AND
# contains no routing verb.

STRICT_PACKET_TYPES = frozenset({"frontend_ui", "backend_api", "infra_ops", "mixed"})
LAX_PACKET_TYPES = frozenset({"review_only", "content_copy", "other"})
LAX_MAX_WORDS = 15

# --- Rule B: near-duplicate detection ------------------------------------

NEAR_DUPLICATE_WINDOW_SECONDS = 300
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.90

# Stripped patterns used during normalization for jaccard comparison.
_STRIP_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_STRIP_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_STRIP_MENTION_RE = re.compile(r"@\w+")
_STRIP_URL_RE = re.compile(r"https?://\S+")
_PUNCT_TO_SPACE_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _has_negative_evidence(message: str) -> bool:
    return any(pattern.search(message) for pattern in _NEG_EVIDENCE_PARTS)


def _has_routing_verb(message: str) -> bool:
    return ROUTING_VERB_RE.search(message) is not None


def _word_count(message: str) -> int:
    return len(message.split())


def _normalize_for_jaccard(message: str) -> str:
    s = _STRIP_CODE_FENCE_RE.sub("", message)
    s = _STRIP_INLINE_CODE_RE.sub("", s)
    s = _STRIP_MENTION_RE.sub("", s)
    s = _STRIP_URL_RE.sub("", s)
    s = _PUNCT_TO_SPACE_RE.sub(" ", s).lower()
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union)
