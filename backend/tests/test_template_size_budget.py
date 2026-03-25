# ruff: noqa: S101
"""Template size guardrails for injected heartbeat context.

The source .j2 file contains multiple branches (main/lead/worker) but only one
is rendered per agent.  We check the RENDERED output for each variant, not the
raw source, because the gateway injects the rendered markdown into context.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

HEARTBEAT_CONTEXT_LIMIT = 20_000
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

    assert "Do not assume exec is blocked based on an earlier session." in rendered
    assert "Attempt the required command once before saying blocked" in rendered
    assert "Only blocked after a fresh tool result says so" in rendered


def test_lead_heartbeat_includes_recovery_endpoint_for_stale_agents() -> None:
    rendered = _render_template(
        "BOARD_HEARTBEAT.md.j2",
        is_main_agent=False,
        is_board_lead=True,
        **_BOARD_RULE_DEFAULTS,
    )

    assert "/api/v1/agent/agents?board_id=$BOARD_ID" in rendered
    assert "agent_status=" in rendered
    assert "Use the literal agent_id from Step 2 output" in rendered
    assert "/api/v1/agent/boards/$BOARD_ID/agents/$AGENT_ID/recover" in rendered
    assert "Recover first, then nudge." in rendered
