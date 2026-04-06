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
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        # Match production renderer settings from provisioning.py _template_env()
        trim_blocks=True,
        lstrip_blocks=True,
    )
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


def test_lead_board_playbook_includes_recovery_and_health_scan() -> None:
    """Phase B2 moved the lead health scan / route / recover / nudge
    content out of BOARD_HEARTBEAT.md.j2 and into BOARD_AGENTS.md.j2's
    ``## Lead Board Playbook`` section. The heartbeat now references
    the playbook by step number; the actual curl commands and the
    Python health-scan script live in AGENTS.md.
    """
    agents_rendered = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        agent_name="Supervisor",
        agent_id="lead-id",
        base_url="http://example.test",
        auth_token="token",
        board_id="board-id",
        **_BOARD_RULE_DEFAULTS,
    )

    # Health-scan endpoints must still be present somewhere the agent
    # can read them — they just live in AGENTS.md now, not HEARTBEAT.md.
    assert "/api/v1/agent/agents?board_id=$BOARD_ID" in agents_rendered, (
        "Lead Board Playbook must contain the health-scan agents endpoint"
    )
    assert "agent_status=" in agents_rendered
    assert "recover" in agents_rendered.lower()
    assert "nudge" in agents_rendered.lower()

    # The HEARTBEAT heartbeat should reference the playbook by name so
    # the model knows where to find the actual curl commands.
    heartbeat_rendered = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        **_BOARD_RULE_DEFAULTS,
    )
    assert "Lead Board Playbook" in heartbeat_rendered, (
        "HEARTBEAT must point workers at AGENTS.md § Lead Board Playbook"
    )


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


def test_agents_md_code_delegation_review_only_flow_for_architect() -> None:
    """Architect agents with ``identity_profile.dev_acp_flow =
    'review_only'`` must render a review/spec-writing delegation
    section — NOT the implementation-oriented default. The Architect's
    IDENTITY says "NEVER write implementation code", so the Code
    Delegation section must not contain "Implement:" task prompts.
    """
    arch_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="Architect",
        agent_id="arch-id",
        identity_dev_acp_flow="review_only",
    )
    assert "## Code Delegation (ACP)" in arch_agents
    assert "Review-only workflow" in arch_agents, (
        "review_only flow must clearly state this is review-only"
    )
    assert "adversarial-review" in arch_agents.lower() or "adversarial review" in arch_agents.lower(), (
        "review_only flow must include the /codex adversarial review pattern"
    )
    # Must NOT have implementation-oriented prompts
    assert '"task": "Implement:' not in arch_agents, (
        "review_only flow MUST NOT contain 'Implement:' task prompts — "
        "the Architect's IDENTITY says NEVER write implementation code"
    )
    assert "Do NOT use the implementation delegation pattern" in arch_agents, (
        "review_only flow must explicitly forbid the implementation pattern"
    )


def test_agents_md_code_delegation_review_only_does_not_render_for_default_workers() -> None:
    """Workers without the review_only flag must NOT get the review-only
    section — they should get the default implementation flow.
    """
    default_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="QA-Unit",
        agent_id="qa-id",
    )
    assert "Review-only workflow" not in default_agents
    assert "Spec Writing" not in default_agents


def test_soul_ralph_loop_step4_is_role_aware() -> None:
    """SOUL.md Ralph Loop step 4 must not unconditionally say 'Delegate
    implementation' — review-only roles (like Architect) must not be
    told to implement. The step should use role-neutral language like
    'Delegate per AGENTS.md' and note the review-only exception.
    """
    worker_soul = _render_template(
        "BOARD_SOUL.md.j2",
        agent_name="Architect",
        is_board_lead=False,
    )
    assert "review-only" in worker_soul.lower() or "review only" in worker_soul.lower(), (
        "SOUL.md step 4 must mention the review-only exception so "
        "Architect knows not to follow the implementation path"
    )
    assert "Delegate implementation per" not in worker_soul, (
        "SOUL.md must not unconditionally say 'Delegate implementation' — "
        "that contradicts Architect IDENTITY's 'NEVER write implementation code'"
    )


def test_soul_skips_oversized_directory_persona_preamble() -> None:
    """Souls Directory can return huge persona preambles (75+ lines of
    generic philosophy). SOUL.md must cap the injection to avoid wasting
    bootstrap tokens on content that has no operational value. Preambles
    over 2000 chars are skipped.
    """
    large_persona = "# Role Persona\n\n" + "Philosophy line.\n" * 200  # ~3400 chars
    soul_with_large = _render_template(
        "BOARD_SOUL.md.j2",
        agent_name="DevOps",
        is_board_lead=False,
        is_main_agent=False,
        directory_role_soul_markdown=large_persona,
    )
    assert "Philosophy line" not in soul_with_large, (
        "SOUL.md must skip Souls Directory persona over 2000 chars"
    )
    assert "Ralph Loop" in soul_with_large, (
        "Ralph Loop section must still render even when persona is skipped"
    )
    assert "skipped" in soul_with_large.lower(), (
        "SOUL.md must include an operator-visible warning when persona is "
        "skipped due to size — silent drops are hard to debug"
    )

    small_persona = "# DevOps Engineer\n\nShort useful guidance."  # ~45 chars
    soul_with_small = _render_template(
        "BOARD_SOUL.md.j2",
        agent_name="DevOps",
        is_board_lead=False,
        is_main_agent=False,
        directory_role_soul_markdown=small_persona,
    )
    assert "Short useful guidance" in soul_with_small, (
        "Small Souls Directory personas (<= 2000 chars) must still render"
    )


def test_qa_agents_get_validation_specific_checklist_not_developer_checklist() -> None:
    """QA agents (QA-Unit, QA-E2E) should get a validation-focused
    VALIDATING checklist, not the developer build/deploy/lint checklist.
    """
    qa_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        **{
            **_REALISTIC_RENDER_CONTEXT,
            "is_main_agent": False,
            "is_board_lead": False,
            "agent_name": "QA-Unit",
            "agent_id": "qa-id",
            "identity_role": "Quality Assurance and Reverse-Mode Validator",
            "identity_validation_flow": "qa_validation",
        },
    )
    assert "CODE EXISTENCE CHECK" in qa_agents, (
        "QA VALIDATING must include code-existence check"
    )
    assert "npm run build" not in qa_agents, (
        "QA agents must NOT get developer build checks (npm run build)"
    )
    assert "systemctl status" not in qa_agents, (
        "QA agents must NOT get deployment health checks"
    )

    # Non-QA worker keeps developer checklist
    dev_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        **{
            **_REALISTIC_RENDER_CONTEXT,
            "is_main_agent": False,
            "is_board_lead": False,
            "agent_name": "Programmer-Frontend",
            "agent_id": "pf-id",
            "identity_role": "Frontend Developer",
        },
    )
    assert "npm run build" in dev_agents, (
        "Developer workers must keep the build check in VALIDATING"
    )
    assert "systemctl status" in dev_agents, (
        "Developer workers must keep the deployment health check"
    )


def test_qa_agents_get_qa_specific_hard_rules_in_identity() -> None:
    """QA agents should see 're-validate with fresh evidence' in HARD
    RULES, not 'implement real changes and show a new commit'.
    """
    qa_identity = _render_template(
        "BOARD_IDENTITY.md.j2",
        agent_name="QA-Unit",
        agent_id="qa-id",
        is_board_lead=False,
        identity_role="Quality Assurance and Reverse-Mode Validator",
        identity_communication_style="methodical",
        identity_emoji=":gear:",
        identity_validation_flow="qa_validation",
    )
    assert "re-validate" in qa_identity.lower(), (
        "QA HARD RULES must mention re-validation"
    )
    assert "implement real changes" not in qa_identity.lower(), (
        "QA agents must NOT see developer-centric 'implement real changes'"
    )
    assert "Fabricating evidence" in qa_identity, (
        "Fabrication rule must apply to ALL agents including QA"
    )

    # Non-QA worker keeps developer hard rules
    dev_identity = _render_template(
        "BOARD_IDENTITY.md.j2",
        agent_name="Programmer-Backend",
        agent_id="pb-id",
        is_board_lead=False,
        identity_role="Backend Developer",
        identity_communication_style="direct",
        identity_emoji=":gear:",
    )
    assert "implement real changes" in dev_identity.lower(), (
        "Developer workers must keep the developer HARD RULES"
    )
    assert "deploy to a different machine" in dev_identity.lower(), (
        "Developer workers must keep the deploy safety rule"
    )


def test_qa_discriminator_does_not_false_positive_on_name_containing_qa() -> None:
    """Regression: an agent named 'QA-Security' with role 'Security
    Auditor' must NOT get the QA validation checklist. The previous
    heuristic (``'QA' in agent_name``) would false-positive on this.
    The stable ``identity_validation_flow`` flag prevents that.
    """
    qa_security = _render_template(
        "BOARD_AGENTS.md.j2",
        **{
            **_REALISTIC_RENDER_CONTEXT,
            "is_main_agent": False,
            "is_board_lead": False,
            "agent_name": "QA-Security",
            "agent_id": "sec-id",
            "identity_role": "Security Auditor",
            # No identity_validation_flow → should get developer checklist
        },
    )
    assert "CODE EXISTENCE CHECK" not in qa_security, (
        "QA-Security with Security Auditor role must NOT get QA checklist — "
        "the discriminator must key on identity_validation_flow, not agent_name"
    )
    assert "npm run build" in qa_security or "ruff check" in qa_security, (
        "QA-Security should get the default developer VALIDATING checklist"
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
