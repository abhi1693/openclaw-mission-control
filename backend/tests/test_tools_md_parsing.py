# ruff: noqa: INP001
"""Regression tests for parsing agent TOOLS.md values."""

from app.services.openclaw.provisioning_db import _parse_tools_md


def test_parse_tools_md_reads_bullet_backtick_assignments() -> None:
    content = """
# TOOLS.md

- `BASE_URL=http://192.168.2.64:8000`
- `AUTH_TOKEN=abc123`
- `AGENT_ID=worker-1`
"""

    values = _parse_tools_md(content)

    assert values["BASE_URL"] == "http://192.168.2.64:8000"
    assert values["AUTH_TOKEN"] == "abc123"
    assert values["AGENT_ID"] == "worker-1"
