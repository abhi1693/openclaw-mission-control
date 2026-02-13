# ruff: noqa: S101
"""Template size guardrails for injected heartbeat context."""

from __future__ import annotations

from pathlib import Path

HEARTBEAT_CONTEXT_LIMIT = 20_000
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def test_heartbeat_templates_fit_in_injected_context_limit() -> None:
    """Heartbeat templates must stay under gateway injected-context truncation limit."""
    targets = (
        "HEARTBEAT_LEAD.md",
        "HEARTBEAT_AGENT.md",
        "MAIN_HEARTBEAT.md",
    )
    for name in targets:
        size = (TEMPLATES_DIR / name).stat().st_size
        assert (
            size <= HEARTBEAT_CONTEXT_LIMIT
        ), f"{name} is {size} chars (limit {HEARTBEAT_CONTEXT_LIMIT})"
