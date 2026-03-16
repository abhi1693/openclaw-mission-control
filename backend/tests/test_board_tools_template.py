from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.services.openclaw.provisioning_db import _parse_tools_md


def test_board_tools_template_parses_identity_fields() -> None:
    env = Environment(
        loader=FileSystemLoader("backend/templates"),
        autoescape=select_autoescape(),
        undefined=StrictUndefined,
    )
    template = env.get_template("BOARD_TOOLS.md.j2")
    rendered = template.render(
        base_url="https://mission-control.example",
        auth_token="secret-token",
        agent_name="Thoth",
        agent_id="agent-123",
        board_id="board-456",
        workspace_root="/tmp/openclaw",
        workspace_path="/tmp/openclaw/workspace-thoth",
        is_main_agent=False,
        is_board_lead=True,
    )

    parsed = _parse_tools_md(rendered)
    assert parsed["AUTH_TOKEN"] == "secret-token"
    assert parsed["BASE_URL"] == "https://mission-control.example"
    assert parsed["AGENT_ID"] == "agent-123"
