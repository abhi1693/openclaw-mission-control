# ruff: noqa: S101
"""Template size guardrails for injected heartbeat context.

The source .j2 file contains multiple branches (main/lead/worker) but only one
is rendered per agent.  We check the RENDERED output for each variant, not the
raw source, because the gateway injects the rendered markdown into context.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

HEARTBEAT_CONTEXT_LIMIT = 10_500
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

_BOARD_RULE_DEFAULTS = {
    "board_rule_require_review_before_done": "true",
    "board_rule_require_approval_for_done": "true",
    "board_rule_comment_required_for_review": "true",
    "board_rule_block_status_changes_with_pending_approval": "true",
    "board_rule_only_lead_can_change_status": "true",
    "board_rule_max_agents": "6",
}


def _render_template(name: str, **context: object) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    return env.get_template(name).render(**context)


def test_heartbeat_templates_fit_in_injected_context_limit() -> None:
    """Each rendered heartbeat variant must stay under gateway injected-context truncation limit."""
    variants = {
        "main": {"is_main_agent": True, "is_board_lead": False},
        "lead": {"is_main_agent": False, "is_board_lead": True, **_BOARD_RULE_DEFAULTS},
        "worker": {"is_main_agent": False, "is_board_lead": False, **_BOARD_RULE_DEFAULTS},
    }
    for variant_name, ctx in variants.items():
        rendered = _render_template("BOARD_HEARTBEAT.md.j2", **ctx)
        size = len(rendered)
        assert size <= HEARTBEAT_CONTEXT_LIMIT, (
            f"BOARD_HEARTBEAT.md.j2 ({variant_name}) renders to {size} chars "
            f"(limit {HEARTBEAT_CONTEXT_LIMIT})"
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
    # SOUL.md is allowed to mention the concept ("delegate via
    # sessions_spawn") as a reference, but it must NOT carry the
    # concrete JSON payload — that's the drift risk. The payload has
    # an ``"agentId": "..."`` field that never appears outside the
    # actual `sessions_spawn` call shape.
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
        **_BOARD_RULE_DEFAULTS,
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


def test_agents_md_code_delegation_programmer_backend_uses_codex_plus_claude_review() -> None:
    """Programmer-Backend's Code Delegation section in AGENTS.md must
    describe a two-stage workflow: Codex implements, Claude Code
    reviews. Two separate `sessions_spawn` calls per task iteration,
    with the review running after the implementation commit exists.
    """
    pb_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="Programmer-Backend",
        agent_id="pb-id",
    )
    assert "## Code Delegation (ACP)" in pb_agents
    assert "Stage 1" in pb_agents and "Stage 2" in pb_agents, (
        "PB must have two distinct ACP stages documented in AGENTS.md"
    )
    assert '"agentId": "codex"' in pb_agents, (
        "PB Stage 1 must use codex as the implementation ACP agent"
    )
    assert '"agentId": "claude"' in pb_agents, (
        "PB Stage 2 must use claude as the review ACP agent"
    )
    assert "Codex implements, Claude Code reviews" in pb_agents
    # Review must run after the implementation commit exists.
    lowered = pb_agents.lower()
    assert "after" in lowered and "commit" in lowered


def test_agents_md_code_delegation_non_pb_workers_keep_single_claude_spawn() -> None:
    """Workers other than Programmer-Backend must keep the single-spawn
    Claude-Code-does-it-all flow (implement + /simplify + /codex review
    inside one ACP session). Only PB uses the two-stage split.
    """
    qa_agents = _render_template(
        "BOARD_AGENTS.md.j2",
        is_main_agent=False,
        is_board_lead=False,
        agent_name="QA-Unit",
        agent_id="qa-id",
    )
    assert '"agentId": "claude"' in qa_agents, (
        "non-PB workers must still see the Claude Code spawn payload"
    )
    assert '"agentId": "codex"' not in qa_agents, (
        "non-PB workers must NOT be switched to the Codex-implementer "
        "flow — that's specific to Programmer-Backend"
    )
    assert "Stage 1" not in qa_agents, (
        "non-PB workers use a single-stage flow, not the two-stage PB flow"
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
