from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import settings
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, ensure_session, openclaw_call
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.users import User

DEFAULT_HEARTBEAT_CONFIG = {"every": "10m", "target": "none"}
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
    "custom_instructions": "identity_custom_instructions",
}

DEFAULT_GATEWAY_FILES = frozenset(
    {
        "AGENTS.md",
        "SOUL.md",
        "SELF.md",
        "AUTONOMY.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOT.md",
        "BOOTSTRAP.md",
        "MEMORY.md",
    }
)

# These files are intended to evolve within the agent workspace. Provision them if missing,
# but avoid overwriting existing content during updates.
#
# Examples:
# - SELF.md: evolving identity/preferences
# - USER.md: human-provided context + lead intake notes
# - MEMORY.md: curated long-term memory (consolidated)
PRESERVE_AGENT_EDITABLE_FILES = frozenset({"SELF.md", "USER.md", "MEMORY.md"})

HEARTBEAT_LEAD_TEMPLATE = "HEARTBEAT_LEAD.md"
HEARTBEAT_AGENT_TEMPLATE = "HEARTBEAT_AGENT.md"
MAIN_TEMPLATE_MAP = {
    "AGENTS.md": "MAIN_AGENTS.md",
    "HEARTBEAT.md": "MAIN_HEARTBEAT.md",
    "USER.md": "MAIN_USER.md",
    "BOOT.md": "MAIN_BOOT.md",
    "TOOLS.md": "MAIN_TOOLS.md",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _templates_root() -> Path:
    return _repo_root() / "templates"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _agent_key(agent: Agent) -> str:
    session_key = agent.openclaw_session_id or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return _slugify(agent.name)


def _heartbeat_config(agent: Agent) -> dict[str, Any]:
    if agent.heartbeat_config:
        return agent.heartbeat_config
    return DEFAULT_HEARTBEAT_CONFIG.copy()


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_templates_root()),
        # Render markdown verbatim (HTML escaping makes it harder for agents to read).
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _heartbeat_template_name(agent: Agent) -> str:
    return HEARTBEAT_LEAD_TEMPLATE if agent.is_board_lead else HEARTBEAT_AGENT_TEMPLATE


def _workspace_path(agent: Agent, workspace_root: str) -> str:
    if not workspace_root:
        raise ValueError("gateway_workspace_root is required")
    root = workspace_root.rstrip("/")
    # Use agent key derived from session key when possible. This prevents collisions for
    # lead agents (session key includes board id) even if multiple boards share the same
    # display name (e.g. "Lead Agent").
    key = _agent_key(agent)
    return f"{root}/workspace-{_slugify(key)}"


def _ensure_workspace_file(
    workspace_path: str,
    name: str,
    content: str,
    *,
    overwrite: bool = False,
) -> None:
    if not workspace_path or not name:
        return
    # `gateway.workspace_root` is sometimes configured as `~/.openclaw`.
    # Expand user here to avoid creating a literal `./~` directory under the backend cwd.
    root = Path(workspace_path).expanduser()
    path = root / name
    if not overwrite and path.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _build_context(
    agent: Agent,
    board: Board,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    if not gateway.workspace_root:
        raise ValueError("gateway_workspace_root is required")
    if not gateway.main_session_key:
        raise ValueError("gateway_main_session_key is required")
    agent_id = str(agent.id)
    workspace_root = gateway.workspace_root
    workspace_path = _workspace_path(agent, workspace_root)
    session_key = agent.openclaw_session_id or ""
    base_url = settings.base_url or "REPLACE_WITH_BASE_URL"
    main_session_key = gateway.main_session_key
    identity_profile: dict[str, Any] = {}
    if isinstance(agent.identity_profile, dict):
        identity_profile = agent.identity_profile
    normalized_identity: dict[str, str] = {}
    for key, value in identity_profile.items():
        if value is None:
            continue
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            if not parts:
                continue
            normalized_identity[key] = ", ".join(parts)
            continue
        text = str(value).strip()
        if text:
            normalized_identity[key] = text
    identity_context = {
        context_key: normalized_identity.get(field, DEFAULT_IDENTITY_PROFILE[field])
        for field, context_key in IDENTITY_PROFILE_FIELDS.items()
    }
    extra_identity_context = {
        context_key: normalized_identity.get(field, "")
        for field, context_key in EXTRA_IDENTITY_PROFILE_FIELDS.items()
    }
    preferred_name = (user.preferred_name or "") if user else ""
    if preferred_name:
        preferred_name = preferred_name.strip().split()[0]
    return {
        "agent_name": agent.name,
        "agent_id": agent_id,
        "board_id": str(board.id),
        "board_name": board.name,
        "board_type": board.board_type,
        "board_objective": board.objective or "",
        "board_success_metrics": json.dumps(board.success_metrics or {}),
        "board_target_date": board.target_date.isoformat() if board.target_date else "",
        "board_goal_confirmed": str(board.goal_confirmed).lower(),
        "is_board_lead": str(agent.is_board_lead).lower(),
        "session_key": session_key,
        "workspace_path": workspace_path,
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": main_session_key,
        "workspace_root": workspace_root,
        "user_name": (user.name or "") if user else "",
        "user_preferred_name": preferred_name,
        "user_pronouns": (user.pronouns or "") if user else "",
        "user_timezone": (user.timezone or "") if user else "",
        "user_notes": (user.notes or "") if user else "",
        "user_context": (user.context or "") if user else "",
        **identity_context,
        **extra_identity_context,
    }


def _build_main_context(
    agent: Agent,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    base_url = settings.base_url or "REPLACE_WITH_BASE_URL"
    identity_profile: dict[str, Any] = {}
    if isinstance(agent.identity_profile, dict):
        identity_profile = agent.identity_profile
    normalized_identity: dict[str, str] = {}
    for key, value in identity_profile.items():
        if value is None:
            continue
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            if not parts:
                continue
            normalized_identity[key] = ", ".join(parts)
            continue
        text = str(value).strip()
        if text:
            normalized_identity[key] = text
    identity_context = {
        context_key: normalized_identity.get(field, DEFAULT_IDENTITY_PROFILE[field])
        for field, context_key in IDENTITY_PROFILE_FIELDS.items()
    }
    extra_identity_context = {
        context_key: normalized_identity.get(field, "")
        for field, context_key in EXTRA_IDENTITY_PROFILE_FIELDS.items()
    }
    preferred_name = (user.preferred_name or "") if user else ""
    if preferred_name:
        preferred_name = preferred_name.strip().split()[0]
    return {
        "agent_name": agent.name,
        "agent_id": str(agent.id),
        "session_key": agent.openclaw_session_id or "",
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": gateway.main_session_key or "",
        "workspace_root": gateway.workspace_root or "",
        "user_name": (user.name or "") if user else "",
        "user_preferred_name": preferred_name,
        "user_pronouns": (user.pronouns or "") if user else "",
        "user_timezone": (user.timezone or "") if user else "",
        "user_notes": (user.notes or "") if user else "",
        "user_context": (user.context or "") if user else "",
        **identity_context,
        **extra_identity_context,
    }


def _session_key(agent: Agent) -> str:
    if agent.openclaw_session_id:
        return agent.openclaw_session_id
    return f"agent:{_agent_key(agent)}:main"


async def _supported_gateway_files(config: GatewayClientConfig) -> set[str]:
    try:
        agents_payload = await openclaw_call("agents.list", config=config)
        agents = []
        default_id = None
        if isinstance(agents_payload, dict):
            agents = list(agents_payload.get("agents") or [])
            default_id = agents_payload.get("defaultId") or agents_payload.get("default_id")
        agent_id = default_id or (agents[0].get("id") if agents else None)
        if not agent_id:
            return set(DEFAULT_GATEWAY_FILES)
        files_payload = await openclaw_call(
            "agents.files.list", {"agentId": agent_id}, config=config
        )
        if isinstance(files_payload, dict):
            files = files_payload.get("files") or []
            supported: set[str] = set()
            for item in files:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if isinstance(name, str) and name:
                    supported.add(name)
            return supported or set(DEFAULT_GATEWAY_FILES)
    except OpenClawGatewayError:
        pass
    return set(DEFAULT_GATEWAY_FILES)


async def _reset_session(session_key: str, config: GatewayClientConfig) -> None:
    if not session_key:
        return
    await openclaw_call("sessions.reset", {"key": session_key}, config=config)


async def _gateway_agent_files_index(
    agent_id: str, config: GatewayClientConfig
) -> dict[str, dict[str, Any]]:
    try:
        payload = await openclaw_call("agents.files.list", {"agentId": agent_id}, config=config)
        if isinstance(payload, dict):
            files = payload.get("files") or []
            index: dict[str, dict[str, Any]] = {}
            for item in files:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if isinstance(name, str) and name:
                    index[name] = cast(dict[str, Any], item)
            return index
    except OpenClawGatewayError:
        pass
    return {}


def _render_agent_files(
    context: dict[str, str],
    agent: Agent,
    file_names: set[str],
    *,
    include_bootstrap: bool,
    template_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    env = _template_env()
    overrides: dict[str, str] = {}
    if agent.identity_template:
        overrides["IDENTITY.md"] = agent.identity_template
    if agent.soul_template:
        overrides["SOUL.md"] = agent.soul_template

    rendered: dict[str, str] = {}
    for name in sorted(file_names):
        if name == "BOOTSTRAP.md" and not include_bootstrap:
            continue
        if name == "HEARTBEAT.md":
            heartbeat_template = (
                template_overrides[name]
                if template_overrides and name in template_overrides
                else _heartbeat_template_name(agent)
            )
            heartbeat_path = _templates_root() / heartbeat_template
            if heartbeat_path.exists():
                rendered[name] = env.get_template(heartbeat_template).render(**context).strip()
                continue
        override = overrides.get(name)
        if override:
            rendered[name] = env.from_string(override).render(**context).strip()
            continue
        template_name = (
            template_overrides[name] if template_overrides and name in template_overrides else name
        )
        path = _templates_root() / template_name
        if path.exists():
            rendered[name] = env.get_template(template_name).render(**context).strip()
            continue
        if name == "MEMORY.md":
            # Back-compat fallback for existing gateways that don't ship a MEMORY.md template.
            rendered[name] = "# MEMORY\n\nBootstrap pending.\n"
            continue
        rendered[name] = ""
    return rendered


async def _gateway_default_agent_id(
    config: GatewayClientConfig,
) -> str | None:
    try:
        payload = await openclaw_call("agents.list", config=config)
    except OpenClawGatewayError:
        return None
    if not isinstance(payload, dict):
        return None
    default_id = payload.get("defaultId") or payload.get("default_id")
    if isinstance(default_id, str) and default_id:
        return default_id
    agents = payload.get("agents") or []
    if isinstance(agents, list) and agents:
        first = agents[0]
        if isinstance(first, dict):
            agent_id = first.get("id")
            if isinstance(agent_id, str) and agent_id:
                return agent_id
    return None


async def _patch_gateway_agent_list(
    agent_id: str,
    workspace_path: str,
    heartbeat: dict[str, Any],
    config: GatewayClientConfig,
) -> None:
    cfg = await openclaw_call("config.get", config=config)
    if not isinstance(cfg, dict):
        raise OpenClawGatewayError("config.get returned invalid payload")
    base_hash = cfg.get("hash")
    data = cfg.get("config") or cfg.get("parsed") or {}
    if not isinstance(data, dict):
        raise OpenClawGatewayError("config.get returned invalid config")
    agents = data.get("agents") or {}
    lst = agents.get("list") or []
    if not isinstance(lst, list):
        raise OpenClawGatewayError("config agents.list is not a list")

    updated = False
    new_list: list[dict[str, Any]] = []
    for entry in lst:
        if isinstance(entry, dict) and entry.get("id") == agent_id:
            new_entry = dict(entry)
            new_entry["workspace"] = workspace_path
            new_entry["heartbeat"] = heartbeat
            new_list.append(new_entry)
            updated = True
        else:
            new_list.append(entry)
    if not updated:
        new_list.append({"id": agent_id, "workspace": workspace_path, "heartbeat": heartbeat})

    patch = {"agents": {"list": new_list}}
    params = {"raw": json.dumps(patch)}
    if base_hash:
        params["baseHash"] = base_hash
    await openclaw_call("config.patch", params, config=config)


async def _remove_gateway_agent_list(
    agent_id: str,
    config: GatewayClientConfig,
) -> None:
    cfg = await openclaw_call("config.get", config=config)
    if not isinstance(cfg, dict):
        raise OpenClawGatewayError("config.get returned invalid payload")
    base_hash = cfg.get("hash")
    data = cfg.get("config") or cfg.get("parsed") or {}
    if not isinstance(data, dict):
        raise OpenClawGatewayError("config.get returned invalid config")
    agents = data.get("agents") or {}
    lst = agents.get("list") or []
    if not isinstance(lst, list):
        raise OpenClawGatewayError("config agents.list is not a list")

    new_list = [
        entry for entry in lst if not (isinstance(entry, dict) and entry.get("id") == agent_id)
    ]
    if len(new_list) == len(lst):
        return
    patch = {"agents": {"list": new_list}}
    params = {"raw": json.dumps(patch)}
    if base_hash:
        params["baseHash"] = base_hash
    await openclaw_call("config.patch", params, config=config)


async def _get_gateway_agent_entry(
    agent_id: str,
    config: GatewayClientConfig,
) -> dict[str, Any] | None:
    cfg = await openclaw_call("config.get", config=config)
    if not isinstance(cfg, dict):
        return None
    data = cfg.get("config") or cfg.get("parsed") or {}
    if not isinstance(data, dict):
        return None
    agents = data.get("agents") or {}
    lst = agents.get("list") or []
    if not isinstance(lst, list):
        return None
    for entry in lst:
        if isinstance(entry, dict) and entry.get("id") == agent_id:
            return entry
    return None


async def provision_agent(
    agent: Agent,
    board: Board,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
    *,
    action: str = "provision",
    force_bootstrap: bool = False,
    reset_session: bool = False,
) -> None:
    if not gateway.url:
        return
    if not gateway.workspace_root:
        raise ValueError("gateway_workspace_root is required")
    client_config = GatewayClientConfig(url=gateway.url, token=gateway.token)
    session_key = _session_key(agent)
    await ensure_session(session_key, config=client_config, label=agent.name)

    agent_id = _agent_key(agent)
    workspace_path = _workspace_path(agent, gateway.workspace_root)
    heartbeat = _heartbeat_config(agent)
    await _patch_gateway_agent_list(agent_id, workspace_path, heartbeat, client_config)

    context = _build_context(agent, board, gateway, auth_token, user)
    supported = set(await _supported_gateway_files(client_config))
    supported.update({"USER.md", "SELF.md", "AUTONOMY.md"})
    existing_files = await _gateway_agent_files_index(agent_id, client_config)
    include_bootstrap = True
    if action == "update" and not force_bootstrap:
        if not existing_files:
            include_bootstrap = False
        else:
            entry = existing_files.get("BOOTSTRAP.md")
            if entry and entry.get("missing") is True:
                include_bootstrap = False

    rendered = _render_agent_files(
        context,
        agent,
        supported,
        include_bootstrap=include_bootstrap,
    )

    # Ensure editable template files exist locally (best-effort) without overwriting.
    for name in PRESERVE_AGENT_EDITABLE_FILES:
        content = rendered.get(name)
        if not content:
            continue
        try:
            _ensure_workspace_file(workspace_path, name, content, overwrite=False)
        except OSError:
            # Local workspace may not be writable/available; fall back to gateway API.
            pass
    for name, content in rendered.items():
        if content == "":
            continue
        if name in PRESERVE_AGENT_EDITABLE_FILES:
            # Never overwrite; only provision if missing.
            entry = existing_files.get(name)
            if entry and entry.get("missing") is not True:
                continue
        try:
            await openclaw_call(
                "agents.files.set",
                {"agentId": agent_id, "name": name, "content": content},
                config=client_config,
            )
        except OpenClawGatewayError as exc:
            # Gateways may restrict file names. Skip unsupported files rather than
            # failing provisioning for the entire agent.
            if "unsupported file" in str(exc).lower():
                continue
            raise
    if reset_session:
        await _reset_session(session_key, client_config)


async def provision_main_agent(
    agent: Agent,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
    *,
    action: str = "provision",
    force_bootstrap: bool = False,
    reset_session: bool = False,
) -> None:
    if not gateway.url:
        return
    if not gateway.main_session_key:
        raise ValueError("gateway main_session_key is required")
    client_config = GatewayClientConfig(url=gateway.url, token=gateway.token)
    await ensure_session(gateway.main_session_key, config=client_config, label="Main Agent")

    agent_id = await _gateway_default_agent_id(client_config)
    if not agent_id:
        raise OpenClawGatewayError("Unable to resolve gateway main agent id")

    context = _build_main_context(agent, gateway, auth_token, user)
    supported = set(await _supported_gateway_files(client_config))
    supported.update({"USER.md", "SELF.md", "AUTONOMY.md"})
    existing_files = await _gateway_agent_files_index(agent_id, client_config)
    include_bootstrap = action != "update" or force_bootstrap
    if action == "update" and not force_bootstrap:
        if not existing_files:
            include_bootstrap = False
        else:
            entry = existing_files.get("BOOTSTRAP.md")
            if entry and entry.get("missing") is True:
                include_bootstrap = False

    rendered = _render_agent_files(
        context,
        agent,
        supported,
        include_bootstrap=include_bootstrap,
        template_overrides=MAIN_TEMPLATE_MAP,
    )
    for name, content in rendered.items():
        if content == "":
            continue
        if name in PRESERVE_AGENT_EDITABLE_FILES:
            entry = existing_files.get(name)
            if entry and entry.get("missing") is not True:
                continue
        try:
            await openclaw_call(
                "agents.files.set",
                {"agentId": agent_id, "name": name, "content": content},
                config=client_config,
            )
        except OpenClawGatewayError as exc:
            if "unsupported file" in str(exc).lower():
                continue
            raise
    if reset_session:
        await _reset_session(gateway.main_session_key, client_config)


async def cleanup_agent(
    agent: Agent,
    gateway: Gateway,
) -> str | None:
    if not gateway.url:
        return None
    if not gateway.workspace_root:
        raise ValueError("gateway_workspace_root is required")
    client_config = GatewayClientConfig(url=gateway.url, token=gateway.token)

    agent_id = _agent_key(agent)
    entry = await _get_gateway_agent_entry(agent_id, client_config)
    await _remove_gateway_agent_list(agent_id, client_config)

    session_key = _session_key(agent)
    await openclaw_call("sessions.delete", {"key": session_key}, config=client_config)

    workspace_path = entry.get("workspace") if entry else None
    if not workspace_path:
        workspace_path = _workspace_path(agent, gateway.workspace_root)
    return workspace_path
