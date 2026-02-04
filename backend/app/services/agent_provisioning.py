from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import settings
from app.integrations.openclaw_gateway import GatewayConfig, ensure_session, send_message
from app.models.agents import Agent
from app.models.boards import Board

TEMPLATE_FILES = [
    "AGENTS.md",
    "BOOT.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "IDENTITY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _templates_root() -> Path:
    return _repo_root() / "templates"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_templates_root()),
        autoescape=select_autoescape(default=True),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _read_templates(context: dict[str, str]) -> dict[str, str]:
    env = _template_env()
    templates: dict[str, str] = {}
    for name in TEMPLATE_FILES:
        path = _templates_root() / name
        if not path.exists():
            templates[name] = ""
            continue
        template = env.get_template(name)
        templates[name] = template.render(**context).strip()
    return templates


def _render_file_block(name: str, content: str) -> str:
    body = content if content else f"# {name}\n\nTODO: add content\n"
    return f"\n{name}\n```md\n{body}\n```\n"


def _workspace_path(agent_name: str, workspace_root: str) -> str:
    root = workspace_root or "~/.openclaw/workspaces"
    root = root.rstrip("/")
    return f"{root}/{_slugify(agent_name)}"


def build_provisioning_message(agent: Agent, board: Board, auth_token: str) -> str:
    agent_id = str(agent.id)
    workspace_root = board.gateway_workspace_root or "~/.openclaw/workspaces"
    workspace_path = _workspace_path(agent.name, workspace_root)
    session_key = agent.openclaw_session_id or ""
    base_url = settings.base_url or "REPLACE_WITH_BASE_URL"
    main_session_key = board.gateway_main_session_key or "agent:main:main"

    context = {
        "agent_name": agent.name,
        "agent_id": agent_id,
        "board_id": str(board.id),
        "session_key": session_key,
        "workspace_path": workspace_path,
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": main_session_key,
        "workspace_root": workspace_root,
        "user_name": "Unset",
        "user_preferred_name": "Unset",
        "user_timezone": "Unset",
        "user_notes": "Fill in user context.",
    }

    templates = _read_templates(context)

    file_blocks = "".join(
        _render_file_block(name, templates.get(name, "")) for name in TEMPLATE_FILES
    )

    return (
        "Provision a new OpenClaw agent workspace.\n\n"
        f"Agent name: {agent.name}\n"
        f"Agent id: {agent_id}\n"
        f"Session key: {session_key}\n"
        f"Workspace path: {workspace_path}\n\n"
        f"Base URL: {base_url}\n"
        f"Auth token: {auth_token}\n\n"
        "Steps:\n"
        "0) IMPORTANT: Do NOT replace or repurpose the main agent. Keep "
        f"{context['main_session_key']} unchanged and its workspace intact.\n"
        "1) Create the workspace directory.\n"
        "2) Write the files below with the exact contents.\n"
        "3) Update TOOLS.md if BASE_URL/AUTH_TOKEN must change.\n"
        "4) Leave BOOTSTRAP.md in place; the agent should run it on first start and delete it.\n"
        "5) Register agent id in OpenClaw so it uses this workspace path "
        "(never overwrite the main agent session).\n\n"
        "Files:" + file_blocks
    )


async def send_provisioning_message(
    agent: Agent,
    board: Board,
    auth_token: str,
) -> None:
    main_session = board.gateway_main_session_key or "agent:main:main"
    if not board.gateway_url:
        return
    config = GatewayConfig(url=board.gateway_url, token=board.gateway_token)
    await ensure_session(main_session, config=config, label="Main Agent")
    message = build_provisioning_message(agent, board, auth_token)
    await send_message(message, session_key=main_session, config=config, deliver=False)
