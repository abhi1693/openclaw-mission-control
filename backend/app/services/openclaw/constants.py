"""Shared constants for lifecycle orchestration services."""

from __future__ import annotations

import random
import re
from datetime import timedelta
from typing import Any

_GATEWAY_OPENCLAW_AGENT_PREFIX = "mc-gateway-"
_GATEWAY_AGENT_PREFIX = f"agent:{_GATEWAY_OPENCLAW_AGENT_PREFIX}"
_GATEWAY_AGENT_SUFFIX = ":main"

DEFAULT_HEARTBEAT_CONFIG: dict[str, Any] = {
    "every": "10m",
    "target": "last",
    "includeReasoning": False,
    # lightContext=False matches the gateway's natural default (see
    # `pi-embedded-BYdcxQ5A.js:338` applyContextModeFilter + `runtime-
    # BXvktGYG.js:1152` bootstrapContextMode) and the OpenClaw docs at
    # https://docs.openclaw.ai/gateway/heartbeat which declare "lightContext=false"
    # as the documented default. In lightweight mode the gateway strips
    # every bootstrap file except HEARTBEAT.md, so the heartbeat session
    # has no TOOLS.md, no AGENTS.md, no IDENTITY.md, and no MEMORY.md —
    # and therefore no way to resolve $BASE_URL / $AUTH_TOKEN / $BOARD_ID
    # for the check-in curl, no way to read operating rules, and no way
    # to post updates. This was a real incident: commit e37a34e flipped
    # the MC default to True for token savings and immediately produced
    # 22 heartbeat "ok" events with zero nudges because the Supervisor
    # could not execute any curl under lightweight mode (see docs/NOTES.md
    # §"Why the Supervisor heartbeat says OK without nudging"). All 8
    # production agents have been on lightContext=False via per-agent DB
    # override since then. This code default aligns MC with the fleet,
    # the gateway default, and the docs. Explicit `lightContext=True`
    # overrides remain possible for agents that genuinely need the
    # minimal-context path, but the post-refactor templates (AGENTS.md
    # playbooks referenced from a slim HEARTBEAT.md) assume full
    # bootstrap context and MUST NOT be paired with lightContext=True.
    "lightContext": False,
    "isolatedSession": True,
}
# Note: gateway-only fields (model, ackMaxChars, prompt) are not included
# here. They are preserved during config.patch merges because the merge
# starts from the existing gateway config and only overwrites MC-managed keys.

# Worker heartbeats disabled (0m) — workers wake via deliver=True only.
# Supervisor heartbeat is 10m. OFFLINE_AFTER must exceed Supervisor interval + grace.
# Workers will show offline after 35m since last deliver session — acceptable.
# TODO: Replace with per-agent offline detection from effective heartbeat interval.
OFFLINE_AFTER = timedelta(minutes=35)
HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL = timedelta(minutes=1)
# Provisioning convergence policy:
# - require first heartbeat/check-in within this deadline after wake
# - must be longer than the longest heartbeat interval (currently 30m for DevOps)
# - previously 30s which caused restart loops for agents with 4m+ intervals:
#   reconcile retried → config.patch → SIGUSR1 restart → timer reset → never fires
# - allow up to 3 wake attempts before giving up
CHECKIN_DEADLINE_AFTER_WAKE = timedelta(minutes=35)
MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN = 3
AGENT_SESSION_PREFIX = "agent"

DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY: dict[str, bool] = {
    # Suppress routine HEARTBEAT_OK delivery by default.
    "showOk": False,
    "showAlerts": True,
    "useIndicator": True,
}

DEFAULT_IDENTITY_PROFILE = {
    "role": "Generalist",
    "communication_style": "direct, concise, practical",
    "emoji": ":gear:",
}

IDENTITY_PROFILE_FIELDS = {
    "role": "identity_role",
    "communication_style": "identity_communication_style",
    "emoji": "identity_emoji",
}

EXTRA_IDENTITY_PROFILE_FIELDS = {
    "autonomy_level": "identity_autonomy_level",
    "verbosity": "identity_verbosity",
    "output_format": "identity_output_format",
    "update_cadence": "identity_update_cadence",
    # Per-agent charter (optional).
    # Used to give agents a "purpose in life" and a distinct vibe.
    "purpose": "identity_purpose",
    "personality": "identity_personality",
    "custom_instructions": "identity_custom_instructions",
    # Per-agent ACP delegation workflow selector. Controls which
    # `## Code Delegation (ACP)` branch a worker renders in AGENTS.md.
    # Valid values:
    #   - ``"claude_single_spawn"`` (default, absent) → one sessions_spawn
    #     with ``agentId: "claude"`` doing implement + /simplify + /codex
    #     review in the same call. Appropriate for most worker roles.
    #   - ``"codex_then_claude_review"`` → two spawns per task: first
    #     Codex implements via ``agentId: "codex"``, then Claude Code
    #     reviews the resulting commit via ``agentId: "claude"`` with
    #     /simplify + /codex adversarial-review. Used for
    #     Programmer-Backend currently.
    #
    # Templates branch on ``identity_dev_acp_flow`` instead of matching
    # ``agent_name == "Programmer-Backend"`` literally — that match was
    # brittle because agent names are editable display fields. This
    # profile field survives renames.
    "dev_acp_flow": "identity_dev_acp_flow",
    # Per-agent validation workflow selector. Controls which VALIDATING
    # checklist and HARD RULES variant a worker renders.
    # Valid values:
    #   - ``"qa_validation"`` → QA-specific checklist (code-existence
    #     check, acceptance-criterion validation, proof-format rules,
    #     re-validate mandate) + QA HARD RULES ("re-validate with fresh
    #     evidence"). Used for QA-Unit and QA-E2E currently.
    #   - absent/default → developer checklist (typecheck, lint, tests,
    #     build, deploy health) + developer HARD RULES ("implement real
    #     changes and show a new commit").
    #
    # Replaces the brittle ``"QA" in identity_role or agent_name``
    # heuristic which would false-positive on agents like "QA-Security"
    # with role "Security Auditor".
    "validation_flow": "identity_validation_flow",
}

DEFAULT_GATEWAY_FILES = frozenset(
    {
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "MEMORY.md",
    },
)

# Lead-only workspace contract. Used for board leads to allow an iterative rollout
# without changing worker templates.
LEAD_GATEWAY_FILES = frozenset(
    {
        "AGENTS.md",
        "BOOTSTRAP.md",
        "IDENTITY.md",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        "TOOLS.md",
        "HEARTBEAT.md",
    },
)

# These files are intended to evolve within the agent workspace.
# Provision them if missing, but avoid overwriting existing content during updates.
#
# Examples:
# - USER.md: human-provided context + lead intake notes
# - MEMORY.md: curated long-term memory (consolidated)
PRESERVE_AGENT_EDITABLE_FILES = frozenset({"USER.md", "MEMORY.md", "IDENTITY.md"})

HEARTBEAT_LEAD_TEMPLATE = "BOARD_HEARTBEAT.md.j2"
HEARTBEAT_AGENT_TEMPLATE = "BOARD_HEARTBEAT.md.j2"
SESSION_KEY_PARTS_MIN = 2
_SESSION_KEY_PARTS_MIN = SESSION_KEY_PARTS_MIN

MAIN_TEMPLATE_MAP = {
    "AGENTS.md": "BOARD_AGENTS.md.j2",
    "IDENTITY.md": "BOARD_IDENTITY.md.j2",
    "SOUL.md": "BOARD_SOUL.md.j2",
    "MEMORY.md": "BOARD_MEMORY.md.j2",
    "HEARTBEAT.md": "BOARD_HEARTBEAT.md.j2",
    "USER.md": "BOARD_USER.md.j2",
    "TOOLS.md": "BOARD_TOOLS.md.j2",
}

BOARD_SHARED_TEMPLATE_MAP = {
    "AGENTS.md": "BOARD_AGENTS.md.j2",
    "BOOTSTRAP.md": "BOARD_BOOTSTRAP.md.j2",
    "IDENTITY.md": "BOARD_IDENTITY.md.j2",
    "SOUL.md": "BOARD_SOUL.md.j2",
    "MEMORY.md": "BOARD_MEMORY.md.j2",
    "HEARTBEAT.md": "BOARD_HEARTBEAT.md.j2",
    "USER.md": "BOARD_USER.md.j2",
    "TOOLS.md": "BOARD_TOOLS.md.j2",
}

LEAD_TEMPLATE_MAP: dict[str, str] = {}

_TOOLS_KV_RE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")
_NON_TRANSIENT_GATEWAY_ERROR_MARKERS = ("unsupported file",)
_TRANSIENT_GATEWAY_ERROR_MARKERS = (
    "connect call failed",
    "connection refused",
    "errno 111",
    "econnrefused",
    "did not receive a valid http response",
    "no route to host",
    "network is unreachable",
    "host is down",
    "name or service not known",
    "received 1012",
    "service restart",
    "http 503",
    "http 502",
    "http 504",
    "temporar",
    "timeout",
    "timed out",
    "connection closed",
    "connection reset",
)

_COORDINATION_GATEWAY_TIMEOUT_S = 45.0
_COORDINATION_GATEWAY_BASE_DELAY_S = 0.5
_COORDINATION_GATEWAY_MAX_DELAY_S = 5.0
_SECURE_RANDOM = random.SystemRandom()
