# ruff: noqa: S101
"""Template size guardrails for injected bootstrap context.

The source .j2 files contain multiple branches (main/lead/worker) but only one
is rendered per agent. We check the RENDERED output for each variant with
realistic provisioning context (matching what ``_build_context`` injects at
runtime) because the gateway injects the rendered markdown into the model's
bootstrap context.

The hard cap aligns with the OpenClaw docs at
https://docs.openclaw.ai/concepts/context which declare
``agents.defaults.bootstrapMaxChars = 20000`` as the per-file cap and
``agents.defaults.bootstrapTotalMaxChars = 150000`` as the total-across-files
cap. Files over the per-file cap get truncated by the gateway, which would
silently drop instructions. The previous ``HEARTBEAT_CONTEXT_LIMIT = 10_500``
guard was fake — nothing in the runtime enforced that number, it was just
test hygiene from a prior era — and it rendered with minimal context so it
lied about headroom. This test now uses the documented runtime contract and
realistic context matching ``_build_context``.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# Docs-backed per-file injection cap:
# https://docs.openclaw.ai/concepts/context — ``agents.defaults.bootstrapMaxChars``
BOOTSTRAP_PER_FILE_MAX_CHARS = 20_000

# Soft budget for HEARTBEAT specifically — prompt-cost hygiene, not a
# runtime contract. Heartbeats fire on every cron tick so a bloated
# HEARTBEAT.md burns tokens on every tick, unlike AGENTS.md which is
# read once per session start.
HEARTBEAT_SOFT_BUDGET = 12_000

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

_BOARD_RULE_DEFAULTS = {
    "board_rule_require_review_before_done": "true",
    "board_rule_require_approval_for_done": "true",
    "board_rule_comment_required_for_review": "true",
    "board_rule_block_status_changes_with_pending_approval": "true",
    "board_rule_only_lead_can_change_status": "true",
    "board_rule_max_agents": "6",
}

# Realistic provisioning context matching what
# ``_build_context`` in ``backend/app/services/openclaw/provisioning.py``
# injects at runtime. Using minimal context in the old test produced a
# fake 10,486-char headroom when the realistic render was 10,512 chars
# — over the (also-fake) 10,500 limit.
_REALISTIC_RENDER_CONTEXT = {
    "agent_name": "Worker-Agent-Sample",
    "agent_id": "00000000-0000-4000-8000-000000000001",
    "board_id": "00000000-0000-4000-8000-000000000002",
    "base_url": "http://192.168.2.64:8000",
    "auth_token": "sample-agent-token-with-realistic-length-000000000000",
    "user_timezone": "America/Sao_Paulo",
    "shared_workspace": "/shared",
    "workspace_path": "/root/.openclaw/workspace/workspace-mc-sample",
    **_BOARD_RULE_DEFAULTS,
}


def _render_template(name: str, **context: object) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    return env.get_template(name).render(**context)


def test_heartbeat_templates_fit_in_bootstrap_per_file_cap() -> None:
    """Each rendered heartbeat variant must stay under the gateway's
    documented per-file bootstrap injection cap (20,000 chars). Files
    over the cap get silently truncated by the gateway which would drop
    instructions. This is the real runtime contract — the old
    ``HEARTBEAT_CONTEXT_LIMIT = 10_500`` was test-only hygiene with no
    runtime enforcement.

    Rendered with realistic context (matching ``_build_context``) because
    minimal-context rendering under-reports the real size.
    """
    variants = {
        "main": {"is_main_agent": True, "is_board_lead": False, **_REALISTIC_RENDER_CONTEXT},
        "lead": {"is_main_agent": False, "is_board_lead": True, **_REALISTIC_RENDER_CONTEXT},
        "worker": {"is_main_agent": False, "is_board_lead": False, **_REALISTIC_RENDER_CONTEXT},
    }
    for variant_name, ctx in variants.items():
        rendered = _render_template("BOARD_HEARTBEAT.md.j2", **ctx)
        size = len(rendered)
        assert size <= BOOTSTRAP_PER_FILE_MAX_CHARS, (
            f"BOARD_HEARTBEAT.md.j2 ({variant_name}) renders to {size} chars "
            f"(docs-backed per-file cap {BOOTSTRAP_PER_FILE_MAX_CHARS})"
        )


def test_heartbeat_templates_stay_within_soft_budget() -> None:
    """Prompt-cost hygiene: HEARTBEAT.md is injected on every cron tick,
    so its size directly impacts per-tick token cost. This test is NOT a
    runtime contract — the gateway only enforces the 20,000-char hard
    cap. It's a soft budget to catch bloat early. If it fires, either
    shrink the template or raise the budget deliberately.
    """
    variants = {
        "main": {"is_main_agent": True, "is_board_lead": False, **_REALISTIC_RENDER_CONTEXT},
        "lead": {"is_main_agent": False, "is_board_lead": True, **_REALISTIC_RENDER_CONTEXT},
        "worker": {"is_main_agent": False, "is_board_lead": False, **_REALISTIC_RENDER_CONTEXT},
    }
    for variant_name, ctx in variants.items():
        rendered = _render_template("BOARD_HEARTBEAT.md.j2", **ctx)
        size = len(rendered)
        assert size <= HEARTBEAT_SOFT_BUDGET, (
            f"BOARD_HEARTBEAT.md.j2 ({variant_name}) renders to {size} chars "
            f"(soft budget {HEARTBEAT_SOFT_BUDGET}) — consider shrinking "
            "or raising the budget deliberately"
        )


def test_agents_md_fits_in_bootstrap_per_file_cap() -> None:
    """AGENTS.md is injected at session start (not every tick) but it
    still has to fit under the gateway's per-file bootstrap cap to avoid
    silent truncation of operating instructions. Since the ACP delegation
    refactor moved playbook content into AGENTS.md, this file is now the
    biggest single contributor to the bootstrap budget.
    """
    variants = {
        "main": {"is_main_agent": True, "is_board_lead": False, **_REALISTIC_RENDER_CONTEXT},
        "lead": {
            "is_main_agent": False,
            "is_board_lead": True,
            "agent_name": "Supervisor",
            **_REALISTIC_RENDER_CONTEXT,
        },
        "worker": {
            "is_main_agent": False,
            "is_board_lead": False,
            "agent_name": "Worker-Agent-Sample",
            **_REALISTIC_RENDER_CONTEXT,
        },
    }
    for variant_name, ctx in variants.items():
        rendered = _render_template("BOARD_AGENTS.md.j2", **ctx)
        size = len(rendered)
        assert size <= BOOTSTRAP_PER_FILE_MAX_CHARS, (
            f"BOARD_AGENTS.md.j2 ({variant_name}) renders to {size} chars "
            f"(docs-backed per-file cap {BOOTSTRAP_PER_FILE_MAX_CHARS})"
        )


def test_lead_bootstrap_requires_fresh_exec_attempt_before_declaring_blocked() -> None:
    rendered = _render_template(
        "BOARD_BOOTSTRAP.md.j2",
        is_board_lead=True,
        base_url="http://example.test",
        auth_token="token",
        board_id="board-id",
        agent_name="Supervisor",
    )

    assert "Do not assume exec is blocked based on an earlier session." in rendered
    assert "Attempt the required command once in this session before saying you are blocked." in rendered
    assert "Only say exec is blocked after a fresh tool result in this session" in rendered


def test_lead_heartbeat_requires_fresh_exec_attempt_before_declaring_blocked() -> None:
    rendered = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        **_BOARD_RULE_DEFAULTS,
    )

    assert "Do not assume exec is blocked" in rendered
    assert "Try the command first" in rendered


def test_lead_heartbeat_includes_recovery_and_health_scan() -> None:
    rendered = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        **_BOARD_RULE_DEFAULTS,
    )

    assert "/api/v1/agent/agents?board_id=$BOARD_ID" in rendered
    assert "agent_status=" in rendered
    assert "recover" in rendered.lower()
    assert "nudge" in rendered.lower()


def test_acp_delegation_lives_in_agents_md_not_in_soul_identity_or_heartbeat() -> None:
    """Architectural guard: per the OpenClaw agent-workspace docs
    (https://docs.openclaw.ai/concepts/agent-workspace), AGENTS.md is
    the canonical home for cross-cutting operating instructions and
    tool-use patterns. SOUL.md is persona/tone/boundaries, IDENTITY.md
    is name/vibe/emoji, and HEARTBEAT.md must stay "tiny" to avoid
    token burn. The ACP `sessions_spawn` JSON payloads therefore belong
    in AGENTS.md only — duplicating them into SOUL, IDENTITY, or
    HEARTBEAT creates drift between three sources of truth.
    """
    worker_soul = _render_template(
        "BOARD_SOUL.md.j2",
        agent_name="Programmer-Backend",
        is_board_lead=False,
    )
    # Stricter guard (Codex round-2 feedback): forbid the literal
    # ``sessions_spawn`` mechanism name, not just the JSON payload.
    # Allowing the mechanism name still leaves drift risk — if the
    # delegation tool ever changes name (e.g. from sessions_spawn to a
    # different spawn API), every template mentioning it would need to
    # be updated. AGENTS.md is the single source of truth for BOTH the
    # payload shape AND the mechanism name.
    assert "sessions_spawn" not in worker_soul, (
        "SOUL.md must not reference the `sessions_spawn` mechanism by "
        "name — delegate per AGENTS.md § Code Delegation (ACP) only"
    )
    assert '"agentId"' not in worker_soul, (
        "SOUL.md must not embed the ACP sessions_spawn JSON payload "
        "(no `\"agentId\"` field) — reference AGENTS.md instead"
    )
    assert "## ACP Delegation" not in worker_soul, (
        "SOUL.md must not have a dedicated ACP Delegation section — "
        "that belongs in AGENTS.md"
    )

    worker_identity = _render_template(
        "BOARD_IDENTITY.md.j2",
        agent_name="Programmer-Backend",
        agent_id="pb-id",
        is_board_lead=False,
        identity_role="Backend Programmer",
        identity_communication_style="direct",
        identity_emoji=":gear:",
    )
    assert "sessions_spawn" not in worker_identity, (
        "IDENTITY.md must not reference `sessions_spawn` — identity is "
        "name/vibe/emoji, not tool-use mechanics"
    )
    assert '"agentId"' not in worker_identity, (
        "IDENTITY.md is for name/vibe/emoji only — no ACP JSON payload"
    )
    assert "ACP Delegation" not in worker_identity, (
        "IDENTITY.md must not have an ACP Delegation section — that "
        "pollutes identity with operational mechanics"
    )

    worker_heartbeat = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        **_REALISTIC_RENDER_CONTEXT,
    )
    assert "sessions_spawn" not in worker_heartbeat, (
        "HEARTBEAT.md must not reference `sessions_spawn` — heartbeat "
        "should be a tiny checklist referencing AGENTS.md for the "
        "delegation mechanism"
    )
    assert '"agentId"' not in worker_heartbeat, (
        "HEARTBEAT.md must stay small — the delegation JSON payload "
        "lives in AGENTS.md and is referenced here, not duplicated"
    )


def test_agents_md_contains_code_delegation_section_for_workers() -> None:
    """AGENTS.md is the authoritative home for ACP delegation
    instructions for workers. This test guards the Code Delegation
    section's presence and ensures leads and main agents do not get
    the worker delegation boilerplate.
    """
    worker_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="QA-Unit",
        agent_id="qa-id",
    )
    assert "## Code Delegation (ACP)" in worker_agents, (
        "AGENTS.md must have a Code Delegation section for workers"
    )
    assert "sessions_spawn" in worker_agents
    assert '"agentId": "claude"' in worker_agents

    lead_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        agent_name="Supervisor",
        agent_id="lead-id",
    )
    assert "## Code Delegation (ACP)" not in lead_agents, (
        "leads delegate by assigning tasks, not by spawning ACP "
        "sessions — the section must be worker-only"
    )

    main_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=True,
        is_board_lead=False,
        agent_name="Main Agent",
        agent_id="main-id",
    )
    assert "## Code Delegation (ACP)" not in main_agents, (
        "main agents are not board workers — the section must not "
        "appear in the main-agent rendering"
    )


def test_agents_md_code_delegation_codex_then_claude_review_flow() -> None:
    """Workers with ``identity_profile.dev_acp_flow =
    'codex_then_claude_review'`` must render a two-stage workflow in
    their AGENTS.md Code Delegation section: Codex implements, Claude
    Code reviews. Two separate spawn payloads, with review running
    after the implementation commit exists.

    This test uses the per-agent flow flag, not the literal agent name.
    The previous implementation branched on ``agent_name ==
    "Programmer-Backend"`` which was brittle — agent names are editable
    display fields, so a rename would silently drop the two-stage flow.
    """
    pb_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="Programmer-Backend",
        agent_id="pb-id",
        identity_dev_acp_flow="codex_then_claude_review",
    )
    assert "## Code Delegation (ACP)" in pb_agents
    assert "Stage 1" in pb_agents and "Stage 2" in pb_agents, (
        "codex_then_claude_review flow must have two distinct ACP stages"
    )
    assert '"agentId": "codex"' in pb_agents, (
        "Stage 1 must use codex as the implementation ACP agent"
    )
    assert '"agentId": "claude"' in pb_agents, (
        "Stage 2 must use claude as the review ACP agent"
    )
    assert "Codex implements, Claude Code reviews" in pb_agents
    # Review must run after the implementation commit exists.
    lowered = pb_agents.lower()
    assert "after" in lowered and "commit" in lowered


def test_agents_md_code_delegation_renamed_programmer_backend_keeps_two_stage_flow() -> None:
    """Regression: if Programmer-Backend is renamed in the DB (agents are
    display-name-editable), the two-stage Codex+Claude flow MUST still
    render because we key on ``identity_profile.dev_acp_flow``, not on
    ``agent_name``. This test would have caught the old brittle
    discriminator.
    """
    renamed_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="Backend Engineer",  # renamed from "Programmer-Backend"
        agent_id="pb-id",
        identity_dev_acp_flow="codex_then_claude_review",
    )
    assert '"agentId": "codex"' in renamed_agents, (
        "renaming the display name must not drop the two-stage flow"
    )
    assert "Stage 1" in renamed_agents and "Stage 2" in renamed_agents


def test_agents_md_code_delegation_default_workers_keep_single_claude_spawn() -> None:
    """Workers without an explicit dev_acp_flow flag (absent, empty, or
    any value other than ``'codex_then_claude_review'``) must render the
    default single-spawn Claude-Code-does-it-all flow.
    """
    default_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="QA-Unit",
        agent_id="qa-id",
        # identity_dev_acp_flow intentionally omitted → default flow
    )
    assert '"agentId": "claude"' in default_agents
    assert '"agentId": "codex"' not in default_agents, (
        "absent flow flag must default to single-spawn Claude Code"
    )
    assert "Stage 1" not in default_agents

    # Even with the literal agent_name "Programmer-Backend", an absent
    # flow flag must NOT trigger the two-stage branch — the template
    # must key on the flag, not the name.
    pb_name_no_flag = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="Programmer-Backend",
        agent_id="pb-id",
        # no identity_dev_acp_flow
    )
    assert '"agentId": "codex"' not in pb_name_no_flag, (
        "template MUST NOT key on agent_name — absent flag means default flow"
    )


def test_soul_and_heartbeat_reference_agents_md_for_delegation() -> None:
    """SOUL.md's Ralph loop and HEARTBEAT.md's IMPLEMENTING state must
    reference AGENTS.md as the source of delegation instructions,
    rather than embedding the JSON payloads themselves. This keeps
    the three files aligned on a single source of truth.
    """
    worker_soul = _render_template(
        "BOARD_SOUL.md.j2",
        agent_name="Programmer-Backend",
        is_board_lead=False,
    )
    assert "AGENTS.md" in worker_soul and "Code Delegation" in worker_soul, (
        "SOUL.md Ralph loop must point at AGENTS.md § Code Delegation"
    )

    worker_heartbeat = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        **_BOARD_RULE_DEFAULTS,
    )
    assert "AGENTS.md" in worker_heartbeat and "Code Delegation" in worker_heartbeat, (
        "HEARTBEAT.md IMPLEMENTING state must point at AGENTS.md § Code Delegation"
    )
