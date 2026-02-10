"""Provisioning, template sync, and board-lead lifecycle orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import func
from sqlmodel import col, select

from app.core.agent_tokens import generate_agent_token, hash_agent_token, verify_agent_token
from app.core.config import settings
from app.core.time import utcnow
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import (
    OpenClawGatewayError,
    ensure_session,
    openclaw_call,
    send_message,
)
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.gateways import GatewayTemplatesSyncError, GatewayTemplatesSyncResult
from app.services.openclaw.constants import (
    _COORDINATION_GATEWAY_BASE_DELAY_S,
    _COORDINATION_GATEWAY_MAX_DELAY_S,
    _COORDINATION_GATEWAY_TIMEOUT_S,
    _NON_TRANSIENT_GATEWAY_ERROR_MARKERS,
    _SECURE_RANDOM,
    _SESSION_KEY_PARTS_MIN,
    _TOOLS_KV_RE,
    _TRANSIENT_GATEWAY_ERROR_MARKERS,
    DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY,
    DEFAULT_GATEWAY_FILES,
    DEFAULT_HEARTBEAT_CONFIG,
    DEFAULT_IDENTITY_PROFILE,
    EXTRA_IDENTITY_PROFILE_FIELDS,
    HEARTBEAT_AGENT_TEMPLATE,
    HEARTBEAT_LEAD_TEMPLATE,
    IDENTITY_PROFILE_FIELDS,
    MAIN_TEMPLATE_MAP,
    PRESERVE_AGENT_EDITABLE_FILES,
)
from app.services.openclaw.shared import GatewayAgentIdentity

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


@dataclass(frozen=True, slots=True)
class ProvisionOptions:
    """Toggles controlling provisioning write/reset behavior."""

    action: str = "provision"
    force_bootstrap: bool = False
    reset_session: bool = False


@dataclass(frozen=True, slots=True)
class AgentProvisionRequest:
    """Inputs required to provision a board-scoped agent."""

    board: Board
    gateway: Gateway
    auth_token: str
    user: User | None
    options: ProvisionOptions = field(default_factory=ProvisionOptions)


@dataclass(frozen=True, slots=True)
class MainAgentProvisionRequest:
    """Inputs required to provision a gateway main agent."""

    gateway: Gateway
    auth_token: str
    user: User | None
    session_key: str | None = None
    options: ProvisionOptions = field(default_factory=ProvisionOptions)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _templates_root() -> Path:
    return _repo_root() / "templates"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _clean_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_agent_id_from_item(item: object) -> str | None:
    if isinstance(item, str):
        return _clean_str(item)
    if not isinstance(item, dict):
        return None
    for key in ("id", "agentId", "agent_id"):
        agent_id = _clean_str(item.get(key))
        if agent_id:
            return agent_id
    return None


def _extract_agent_id_from_list(items: object) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        agent_id = _extract_agent_id_from_item(item)
        if agent_id:
            return agent_id
    return None


def _extract_agent_id(payload: object) -> str | None:
    default_keys = ("defaultId", "default_id", "defaultAgentId", "default_agent_id")
    collection_keys = ("agents", "items", "list", "data")

    if isinstance(payload, list):
        return _extract_agent_id_from_list(payload)
    if not isinstance(payload, dict):
        return None
    for key in default_keys:
        agent_id = _clean_str(payload.get(key))
        if agent_id:
            return agent_id
    for key in collection_keys:
        agent_id = _extract_agent_id_from_list(payload.get(key))
        if agent_id:
            return agent_id
    return None


def _agent_key(agent: Agent) -> str:
    session_key = agent.openclaw_session_id or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= _SESSION_KEY_PARTS_MIN and parts[1]:
            return parts[1]
    return _slugify(agent.name)


def _heartbeat_config(agent: Agent) -> dict[str, Any]:
    merged = DEFAULT_HEARTBEAT_CONFIG.copy()
    if isinstance(agent.heartbeat_config, dict):
        merged.update(agent.heartbeat_config)
    return merged


def _channel_heartbeat_visibility_patch(config_data: dict[str, Any]) -> dict[str, Any] | None:
    channels = config_data.get("channels")
    if not isinstance(channels, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}
    defaults = channels.get("defaults")
    if not isinstance(defaults, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}
    heartbeat = defaults.get("heartbeat")
    if not isinstance(heartbeat, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}
    merged = dict(heartbeat)
    changed = False
    for key, value in DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.items():
        if key not in merged:
            merged[key] = value
            changed = True
    if not changed:
        return None
    return {"defaults": {"heartbeat": merged}}


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
        msg = "gateway_workspace_root is required"
        raise ValueError(msg)
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
    # Only write to a dedicated, explicitly-configured local directory.
    # Using `gateway.workspace_root` directly here is unsafe.
    # CodeQL correctly flags that value because it is DB-backed config.
    base_root = (settings.local_agent_workspace_root or "").strip()
    if not base_root:
        return
    base = Path(base_root).expanduser()

    # Derive a stable, safe directory name from the untrusted workspace path.
    # This prevents path traversal and avoids writing to arbitrary locations.
    digest = hashlib.sha256(workspace_path.encode("utf-8")).hexdigest()[:16]
    root = base / f"gateway-workspace-{digest}"

    # Ensure `name` is a plain filename (no path separators).
    if Path(name).name != name:
        return
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
        msg = "gateway_workspace_root is required"
        raise ValueError(msg)
    agent_id = str(agent.id)
    workspace_root = gateway.workspace_root
    workspace_path = _workspace_path(agent, workspace_root)
    session_key = agent.openclaw_session_id or ""
    base_url = settings.base_url or "REPLACE_WITH_BASE_URL"
    main_session_key = GatewayAgentIdentity.session_key(gateway)
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
        "main_session_key": GatewayAgentIdentity.session_key(gateway),
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
            # Back-compat fallback for gateways that do not ship MEMORY.md.
            rendered[name] = "# MEMORY\n\nBootstrap pending.\n"
            continue
        rendered[name] = ""
    return rendered


@dataclass(frozen=True, slots=True)
class GatewayAgentRegistration:
    """Desired gateway runtime state for one agent."""

    agent_id: str
    name: str
    workspace_path: str
    heartbeat: dict[str, Any]


class GatewayControlPlane(ABC):
    """Abstract gateway runtime interface used by agent lifecycle managers."""

    @abstractmethod
    async def ensure_agent_session(self, session_key: str, *, label: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def reset_agent_session(self, session_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent_session(self, session_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upsert_agent(self, registration: GatewayAgentRegistration) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_supported_files(self) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    async def list_agent_files(self, agent_id: str) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def patch_agent_heartbeats(
        self,
        entries: list[tuple[str, str, dict[str, Any]]],
    ) -> None:
        raise NotImplementedError


class OpenClawGatewayControlPlane(GatewayControlPlane):
    """OpenClaw gateway RPC implementation of the lifecycle control-plane contract."""

    def __init__(self, config: GatewayClientConfig) -> None:
        self._config = config

    async def ensure_agent_session(self, session_key: str, *, label: str | None = None) -> None:
        if not session_key:
            return
        await ensure_session(session_key, config=self._config, label=label)

    async def reset_agent_session(self, session_key: str) -> None:
        if not session_key:
            return
        await openclaw_call("sessions.reset", {"key": session_key}, config=self._config)

    async def delete_agent_session(self, session_key: str) -> None:
        if not session_key:
            return
        await openclaw_call("sessions.delete", {"key": session_key}, config=self._config)

    async def _agent_ids(self) -> set[str]:
        payload = await openclaw_call("agents.list", config=self._config)
        raw_agents: object = payload
        if isinstance(payload, dict):
            raw_agents = payload.get("agents") or []
        if not isinstance(raw_agents, list):
            return set()
        ids: set[str] = set()
        for item in raw_agents:
            agent_id = _extract_agent_id_from_item(item)
            if agent_id:
                ids.add(agent_id)
        return ids

    async def upsert_agent(self, registration: GatewayAgentRegistration) -> None:
        agent_ids = await self._agent_ids()
        if registration.agent_id in agent_ids:
            await openclaw_call(
                "agents.update",
                {
                    "agentId": registration.agent_id,
                    "name": registration.name,
                    "workspace": registration.workspace_path,
                },
                config=self._config,
            )
        else:
            # `agents.create` derives `agentId` from `name`, so create with the target id
            # and then set the human-facing name in a follow-up update.
            await openclaw_call(
                "agents.create",
                {
                    "name": registration.agent_id,
                    "workspace": registration.workspace_path,
                },
                config=self._config,
            )
            if registration.name != registration.agent_id:
                await openclaw_call(
                    "agents.update",
                    {
                        "agentId": registration.agent_id,
                        "name": registration.name,
                        "workspace": registration.workspace_path,
                    },
                    config=self._config,
                )
        await self.patch_agent_heartbeats(
            [(registration.agent_id, registration.workspace_path, registration.heartbeat)],
        )

    async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
        await openclaw_call(
            "agents.delete",
            {"agentId": agent_id, "deleteFiles": delete_files},
            config=self._config,
        )

    async def list_supported_files(self) -> set[str]:
        agents_payload = await openclaw_call("agents.list", config=self._config)
        agent_id = _extract_agent_id(agents_payload)
        if not agent_id:
            return set(DEFAULT_GATEWAY_FILES)
        files_payload = await openclaw_call(
            "agents.files.list",
            {"agentId": agent_id},
            config=self._config,
        )
        if not isinstance(files_payload, dict):
            return set(DEFAULT_GATEWAY_FILES)
        files = files_payload.get("files") or []
        if not isinstance(files, list):
            return set(DEFAULT_GATEWAY_FILES)
        supported: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name:
                supported.add(name)
        return supported or set(DEFAULT_GATEWAY_FILES)

    async def list_agent_files(self, agent_id: str) -> dict[str, dict[str, Any]]:
        payload = await openclaw_call(
            "agents.files.list",
            {"agentId": agent_id},
            config=self._config,
        )
        if not isinstance(payload, dict):
            return {}
        files = payload.get("files") or []
        if not isinstance(files, list):
            return {}
        index: dict[str, dict[str, Any]] = {}
        for item in files:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name:
                index[name] = dict(item)
        return index

    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        await openclaw_call(
            "agents.files.set",
            {"agentId": agent_id, "name": name, "content": content},
            config=self._config,
        )

    async def patch_agent_heartbeats(
        self,
        entries: list[tuple[str, str, dict[str, Any]]],
    ) -> None:
        base_hash, raw_list, config_data = await _gateway_config_agent_list(self._config)
        entry_by_id = _heartbeat_entry_map(entries)
        new_list = _updated_agent_list(raw_list, entry_by_id)

        patch: dict[str, Any] = {"agents": {"list": new_list}}
        channels_patch = _channel_heartbeat_visibility_patch(config_data)
        if channels_patch is not None:
            patch["channels"] = channels_patch
        params = {"raw": json.dumps(patch)}
        if base_hash:
            params["baseHash"] = base_hash
        await openclaw_call("config.patch", params, config=self._config)


async def _gateway_config_agent_list(
    config: GatewayClientConfig,
) -> tuple[str | None, list[object], dict[str, Any]]:
    cfg = await openclaw_call("config.get", config=config)
    if not isinstance(cfg, dict):
        msg = "config.get returned invalid payload"
        raise OpenClawGatewayError(msg)

    data = cfg.get("config") or cfg.get("parsed") or {}
    if not isinstance(data, dict):
        msg = "config.get returned invalid config"
        raise OpenClawGatewayError(msg)

    agents_section = data.get("agents") or {}
    agents_list = agents_section.get("list") or []
    if not isinstance(agents_list, list):
        msg = "config agents.list is not a list"
        raise OpenClawGatewayError(msg)
    return cfg.get("hash"), agents_list, data


def _heartbeat_entry_map(
    entries: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        agent_id: (workspace_path, heartbeat) for agent_id, workspace_path, heartbeat in entries
    }


def _updated_agent_list(
    raw_list: list[object],
    entry_by_id: dict[str, tuple[str, dict[str, Any]]],
) -> list[object]:
    updated_ids: set[str] = set()
    new_list: list[object] = []

    for raw_entry in raw_list:
        if not isinstance(raw_entry, dict):
            new_list.append(raw_entry)
            continue
        agent_id = raw_entry.get("id")
        if not isinstance(agent_id, str) or agent_id not in entry_by_id:
            new_list.append(raw_entry)
            continue

        workspace_path, heartbeat = entry_by_id[agent_id]
        new_entry = dict(raw_entry)
        new_entry["workspace"] = workspace_path
        new_entry["heartbeat"] = heartbeat
        new_list.append(new_entry)
        updated_ids.add(agent_id)

    for agent_id, (workspace_path, heartbeat) in entry_by_id.items():
        if agent_id in updated_ids:
            continue
        new_list.append(
            {"id": agent_id, "workspace": workspace_path, "heartbeat": heartbeat},
        )

    return new_list


class BaseAgentLifecycleManager(ABC):
    """Base class for scalable board/main agent lifecycle managers."""

    def __init__(self, gateway: Gateway, control_plane: GatewayControlPlane) -> None:
        self._gateway = gateway
        self._control_plane = control_plane

    @abstractmethod
    def _agent_id(self, agent: Agent) -> str:
        raise NotImplementedError

    @abstractmethod
    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        raise NotImplementedError

    def _template_overrides(self) -> dict[str, str] | None:
        return None

    async def _set_agent_files(
        self,
        *,
        agent_id: str,
        rendered: dict[str, str],
        existing_files: dict[str, dict[str, Any]],
    ) -> None:
        for name, content in rendered.items():
            if content == "":
                continue
            if name in PRESERVE_AGENT_EDITABLE_FILES:
                entry = existing_files.get(name)
                if entry and not bool(entry.get("missing")):
                    continue
            try:
                await self._control_plane.set_agent_file(
                    agent_id=agent_id,
                    name=name,
                    content=content,
                )
            except OpenClawGatewayError as exc:
                if "unsupported file" in str(exc).lower():
                    continue
                raise

    async def provision(
        self,
        *,
        agent: Agent,
        session_key: str,
        auth_token: str,
        user: User | None,
        options: ProvisionOptions,
        board: Board | None = None,
        session_label: str | None = None,
    ) -> None:
        if not self._gateway.workspace_root:
            msg = "gateway_workspace_root is required"
            raise ValueError(msg)
        if not agent.openclaw_session_id:
            agent.openclaw_session_id = session_key
        await self._control_plane.ensure_agent_session(
            session_key,
            label=session_label or agent.name,
        )

        agent_id = self._agent_id(agent)
        workspace_path = _workspace_path(agent, self._gateway.workspace_root)
        heartbeat = _heartbeat_config(agent)
        await self._control_plane.upsert_agent(
            GatewayAgentRegistration(
                agent_id=agent_id,
                name=agent.name,
                workspace_path=workspace_path,
                heartbeat=heartbeat,
            ),
        )

        context = self._build_context(
            agent=agent,
            auth_token=auth_token,
            user=user,
            board=board,
        )
        supported = await self._control_plane.list_supported_files()
        supported.update({"USER.md", "SELF.md", "AUTONOMY.md"})
        existing_files = await self._control_plane.list_agent_files(agent_id)
        include_bootstrap = _should_include_bootstrap(
            action=options.action,
            force_bootstrap=options.force_bootstrap,
            existing_files=existing_files,
        )
        rendered = _render_agent_files(
            context,
            agent,
            supported,
            include_bootstrap=include_bootstrap,
            template_overrides=self._template_overrides(),
        )

        for name in PRESERVE_AGENT_EDITABLE_FILES:
            content = rendered.get(name)
            if not content:
                continue
            with suppress(OSError):
                _ensure_workspace_file(workspace_path, name, content, overwrite=False)

        await self._set_agent_files(
            agent_id=agent_id,
            rendered=rendered,
            existing_files=existing_files,
        )
        if options.reset_session:
            await self._control_plane.reset_agent_session(session_key)


class BoardAgentLifecycleManager(BaseAgentLifecycleManager):
    """Provisioning manager for board-scoped agents."""

    def _agent_id(self, agent: Agent) -> str:
        return _agent_key(agent)

    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        if board is None:
            msg = "board is required for board-scoped agent provisioning"
            raise ValueError(msg)
        return _build_context(agent, board, self._gateway, auth_token, user)


class GatewayMainAgentLifecycleManager(BaseAgentLifecycleManager):
    """Provisioning manager for organization gateway-main agents."""

    def _agent_id(self, agent: Agent) -> str:
        return GatewayAgentIdentity.openclaw_agent_id(self._gateway)

    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        _ = board
        return _build_main_context(agent, self._gateway, auth_token, user)

    def _template_overrides(self) -> dict[str, str] | None:
        return MAIN_TEMPLATE_MAP


def _control_plane_for_gateway(gateway: Gateway) -> OpenClawGatewayControlPlane:
    if not gateway.url:
        msg = "Gateway url is required"
        raise OpenClawGatewayError(msg)
    return OpenClawGatewayControlPlane(
        GatewayClientConfig(url=gateway.url, token=gateway.token),
    )


async def patch_gateway_agent_heartbeats(
    gateway: Gateway,
    *,
    entries: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """Patch multiple agent heartbeat configs in a single gateway config.patch call.

    Each entry is (agent_id, workspace_path, heartbeat_dict).
    """
    control_plane = _control_plane_for_gateway(gateway)
    await control_plane.patch_agent_heartbeats(entries)


async def sync_gateway_agent_heartbeats(gateway: Gateway, agents: list[Agent]) -> None:
    """Sync current Agent.heartbeat_config values to the gateway config."""
    if not gateway.workspace_root:
        msg = "gateway workspace_root is required"
        raise OpenClawGatewayError(msg)
    entries: list[tuple[str, str, dict[str, Any]]] = []
    for agent in agents:
        agent_id = _agent_key(agent)
        workspace_path = _workspace_path(agent, gateway.workspace_root)
        heartbeat = _heartbeat_config(agent)
        entries.append((agent_id, workspace_path, heartbeat))
    if not entries:
        return
    await patch_gateway_agent_heartbeats(gateway, entries=entries)


def _should_include_bootstrap(
    *,
    action: str,
    force_bootstrap: bool,
    existing_files: dict[str, dict[str, Any]],
) -> bool:
    if action != "update" or force_bootstrap:
        return True
    if not existing_files:
        return False
    entry = existing_files.get("BOOTSTRAP.md")
    return not bool(entry and entry.get("missing"))


async def provision_agent(
    agent: Agent,
    request: AgentProvisionRequest,
) -> None:
    """Provision or update a regular board agent workspace."""
    gateway = request.gateway
    if not gateway.url:
        return
    session_key = _session_key(agent)
    control_plane = _control_plane_for_gateway(gateway)
    manager = BoardAgentLifecycleManager(gateway, control_plane)
    await manager.provision(
        agent=agent,
        board=request.board,
        session_key=session_key,
        auth_token=request.auth_token,
        user=request.user,
        options=request.options,
    )


async def provision_main_agent(
    agent: Agent,
    request: MainAgentProvisionRequest,
) -> None:
    """Provision or update the gateway main agent workspace."""
    gateway = request.gateway
    if not gateway.url:
        return
    session_key = (request.session_key or GatewayAgentIdentity.session_key(gateway) or "").strip()
    if not session_key:
        msg = "gateway main agent session_key is required"
        raise ValueError(msg)
    control_plane = _control_plane_for_gateway(gateway)
    manager = GatewayMainAgentLifecycleManager(gateway, control_plane)
    await manager.provision(
        agent=agent,
        session_key=session_key,
        auth_token=request.auth_token,
        user=request.user,
        options=request.options,
        session_label=agent.name or "Gateway Agent",
    )


async def cleanup_agent(
    agent: Agent,
    gateway: Gateway,
) -> str | None:
    """Remove an agent from gateway config and delete its session."""
    if not gateway.url:
        return None
    if not gateway.workspace_root:
        msg = "gateway_workspace_root is required"
        raise ValueError(msg)
    control_plane = _control_plane_for_gateway(gateway)
    agent_id = _agent_key(agent)
    await control_plane.delete_agent(agent_id, delete_files=True)

    session_key = _session_key(agent)
    with suppress(OpenClawGatewayError):
        await control_plane.delete_agent_session(session_key)
    return None


_T = TypeVar("_T")


@dataclass(frozen=True)
class GatewayTemplateSyncOptions:
    """Runtime options controlling gateway template synchronization."""

    user: User | None
    include_main: bool = True
    reset_sessions: bool = False
    rotate_tokens: bool = False
    force_bootstrap: bool = False
    board_id: UUID | None = None


@dataclass(frozen=True)
class _SyncContext:
    """Shared state passed to sync helper functions."""

    session: AsyncSession
    gateway: Gateway
    config: GatewayClientConfig
    backoff: _GatewayBackoff
    options: GatewayTemplateSyncOptions


def _is_transient_gateway_error(exc: Exception) -> bool:
    if not isinstance(exc, OpenClawGatewayError):
        return False
    message = str(exc).lower()
    if not message:
        return False
    if any(marker in message for marker in _NON_TRANSIENT_GATEWAY_ERROR_MARKERS):
        return False
    return ("503" in message and "websocket" in message) or any(
        marker in message for marker in _TRANSIENT_GATEWAY_ERROR_MARKERS
    )


def _gateway_timeout_message(
    exc: OpenClawGatewayError,
    *,
    timeout_s: float,
    context: str,
) -> str:
    rounded_timeout = int(timeout_s)
    timeout_text = f"{rounded_timeout} seconds"
    if rounded_timeout >= 120:
        timeout_text = f"{rounded_timeout // 60} minutes"
    return f"Gateway unreachable after {timeout_text} ({context} timeout). Last error: {exc}"


class _GatewayBackoff:
    def __init__(
        self,
        *,
        timeout_s: float = 10 * 60,
        base_delay_s: float = 0.75,
        max_delay_s: float = 30.0,
        jitter: float = 0.2,
        timeout_context: str = "gateway operation",
    ) -> None:
        self._timeout_s = timeout_s
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._jitter = jitter
        self._timeout_context = timeout_context
        self._delay_s = base_delay_s

    def reset(self) -> None:
        self._delay_s = self._base_delay_s

    @staticmethod
    async def _attempt(
        fn: Callable[[], Awaitable[_T]],
    ) -> tuple[_T | None, OpenClawGatewayError | None]:
        try:
            return await fn(), None
        except OpenClawGatewayError as exc:
            return None, exc

    async def run(self, fn: Callable[[], Awaitable[_T]]) -> _T:
        # Use per-call deadlines so long-running syncs can still tolerate a later
        # gateway restart without having an already-expired retry window.
        deadline_s = asyncio.get_running_loop().time() + self._timeout_s
        while True:
            value, error = await self._attempt(fn)
            if error is not None:
                exc = error
                if not _is_transient_gateway_error(exc):
                    raise exc
                now = asyncio.get_running_loop().time()
                remaining = deadline_s - now
                if remaining <= 0:
                    raise TimeoutError(
                        _gateway_timeout_message(
                            exc,
                            timeout_s=self._timeout_s,
                            context=self._timeout_context,
                        ),
                    ) from exc

                sleep_s = min(self._delay_s, remaining)
                if self._jitter:
                    sleep_s *= 1.0 + _SECURE_RANDOM.uniform(
                        -self._jitter,
                        self._jitter,
                    )
                sleep_s = max(0.0, min(sleep_s, remaining))
                await asyncio.sleep(sleep_s)
                self._delay_s = min(self._delay_s * 2.0, self._max_delay_s)
                continue
            self.reset()
            if value is None:
                msg = "Gateway retry produced no value without an error"
                raise RuntimeError(msg)
            return value


async def _with_gateway_retry(
    fn: Callable[[], Awaitable[_T]],
    *,
    backoff: _GatewayBackoff,
) -> _T:
    return await backoff.run(fn)


async def _with_coordination_gateway_retry(fn: Callable[[], Awaitable[_T]]) -> _T:
    return await _with_gateway_retry(
        fn,
        backoff=_GatewayBackoff(
            timeout_s=_COORDINATION_GATEWAY_TIMEOUT_S,
            base_delay_s=_COORDINATION_GATEWAY_BASE_DELAY_S,
            max_delay_s=_COORDINATION_GATEWAY_MAX_DELAY_S,
            jitter=0.15,
            timeout_context="gateway coordination",
        ),
    )


def _parse_tools_md(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TOOLS_KV_RE.match(line)
        if not match:
            continue
        values[match.group("key")] = match.group("value").strip()
    return values


async def _get_agent_file(
    *,
    agent_gateway_id: str,
    name: str,
    config: GatewayClientConfig,
    backoff: _GatewayBackoff | None = None,
) -> str | None:
    try:

        async def _do_get() -> object:
            return await openclaw_call(
                "agents.files.get",
                {"agentId": agent_gateway_id, "name": name},
                config=config,
            )

        payload = await (backoff.run(_do_get) if backoff else _do_get())
    except OpenClawGatewayError:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content
        file_obj = payload.get("file")
        if isinstance(file_obj, dict):
            nested = file_obj.get("content")
            if isinstance(nested, str):
                return nested
    return None


async def _get_existing_auth_token(
    *,
    agent_gateway_id: str,
    config: GatewayClientConfig,
    backoff: _GatewayBackoff | None = None,
) -> str | None:
    tools = await _get_agent_file(
        agent_gateway_id=agent_gateway_id,
        name="TOOLS.md",
        config=config,
        backoff=backoff,
    )
    if not tools:
        return None
    values = _parse_tools_md(tools)
    token = values.get("AUTH_TOKEN")
    if not token:
        return None
    token = token.strip()
    return token or None


async def _paused_board_ids(session: AsyncSession, board_ids: list[UUID]) -> set[UUID]:
    if not board_ids:
        return set()

    commands = {"/pause", "/resume"}
    statement = (
        select(BoardMemory.board_id, BoardMemory.content)
        .where(col(BoardMemory.board_id).in_(board_ids))
        .where(col(BoardMemory.is_chat).is_(True))
        .where(func.lower(func.trim(col(BoardMemory.content))).in_(commands))
        .order_by(col(BoardMemory.board_id), col(BoardMemory.created_at).desc())
        # Postgres: DISTINCT ON (board_id) to get latest command per board.
        .distinct(col(BoardMemory.board_id))
    )

    paused: set[UUID] = set()
    for board_id, content in await session.exec(statement):
        cmd = (content or "").strip().lower()
        if cmd == "/pause":
            paused.add(board_id)
    return paused


def _append_sync_error(
    result: GatewayTemplatesSyncResult,
    *,
    message: str,
    agent: Agent | None = None,
    board: Board | None = None,
) -> None:
    result.errors.append(
        GatewayTemplatesSyncError(
            agent_id=agent.id if agent else None,
            agent_name=agent.name if agent else None,
            board_id=board.id if board else None,
            message=message,
        ),
    )


async def _rotate_agent_token(session: AsyncSession, agent: Agent) -> str:
    token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(token)
    agent.updated_at = utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return token


async def _ping_gateway(ctx: _SyncContext, result: GatewayTemplatesSyncResult) -> bool:
    try:

        async def _do_ping() -> object:
            return await openclaw_call("agents.list", config=ctx.config)

        await ctx.backoff.run(_do_ping)
    except (TimeoutError, OpenClawGatewayError) as exc:
        _append_sync_error(result, message=str(exc))
        return False
    else:
        return True


def _base_result(
    gateway: Gateway,
    *,
    include_main: bool,
    reset_sessions: bool,
) -> GatewayTemplatesSyncResult:
    return GatewayTemplatesSyncResult(
        gateway_id=gateway.id,
        include_main=include_main,
        reset_sessions=reset_sessions,
        agents_updated=0,
        agents_skipped=0,
        main_updated=False,
    )


def _boards_by_id(
    boards: list[Board],
    *,
    board_id: UUID | None,
) -> dict[UUID, Board] | None:
    boards_by_id = {board.id: board for board in boards}
    if board_id is None:
        return boards_by_id
    board = boards_by_id.get(board_id)
    if board is None:
        return None
    return {board_id: board}


async def _resolve_agent_auth_token(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
    agent: Agent,
    board: Board | None,
    *,
    agent_gateway_id: str,
) -> tuple[str | None, bool]:
    try:
        auth_token = await _get_existing_auth_token(
            agent_gateway_id=agent_gateway_id,
            config=ctx.config,
            backoff=ctx.backoff,
        )
    except TimeoutError as exc:
        _append_sync_error(result, agent=agent, board=board, message=str(exc))
        return None, True

    if not auth_token:
        if not ctx.options.rotate_tokens:
            result.agents_skipped += 1
            _append_sync_error(
                result,
                agent=agent,
                board=board,
                message=(
                    "Skipping agent: unable to read AUTH_TOKEN from TOOLS.md "
                    "(run with rotate_tokens=true to re-key)."
                ),
            )
            return None, False
        auth_token = await _rotate_agent_token(ctx.session, agent)

    if agent.agent_token_hash and not verify_agent_token(
        auth_token,
        agent.agent_token_hash,
    ):
        if ctx.options.rotate_tokens:
            auth_token = await _rotate_agent_token(ctx.session, agent)
        else:
            _append_sync_error(
                result,
                agent=agent,
                board=board,
                message=(
                    "Warning: AUTH_TOKEN in TOOLS.md does not match backend "
                    "token hash (agent auth may be broken)."
                ),
            )
    return auth_token, False


async def _sync_one_agent(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
    agent: Agent,
    board: Board,
) -> bool:
    auth_token, fatal = await _resolve_agent_auth_token(
        ctx,
        result,
        agent,
        board,
        agent_gateway_id=_agent_key(agent),
    )
    if fatal:
        return True
    if not auth_token:
        return False
    try:

        async def _do_provision() -> bool:
            await provision_agent(
                agent,
                AgentProvisionRequest(
                    board=board,
                    gateway=ctx.gateway,
                    auth_token=auth_token,
                    user=ctx.options.user,
                    options=ProvisionOptions(
                        action="update",
                        force_bootstrap=ctx.options.force_bootstrap,
                        reset_session=ctx.options.reset_sessions,
                    ),
                ),
            )
            return True

        await _with_gateway_retry(_do_provision, backoff=ctx.backoff)
        result.agents_updated += 1
    except TimeoutError as exc:  # pragma: no cover - gateway/network dependent
        result.agents_skipped += 1
        _append_sync_error(result, agent=agent, board=board, message=str(exc))
        return True
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        result.agents_skipped += 1
        _append_sync_error(
            result,
            agent=agent,
            board=board,
            message=f"Failed to sync templates: {exc}",
        )
        return False
    else:
        return False


async def _sync_main_agent(
    ctx: _SyncContext,
    result: GatewayTemplatesSyncResult,
) -> bool:
    main_session_key = GatewayAgentIdentity.session_key(ctx.gateway)
    main_agent = (
        await Agent.objects.all()
        .filter(col(Agent.gateway_id) == ctx.gateway.id)
        .filter(col(Agent.board_id).is_(None))
        .first(ctx.session)
    )
    if main_agent is None:
        _append_sync_error(
            result,
            message="Gateway agent record not found; " "skipping gateway agent template sync.",
        )
        return True
    main_gateway_agent_id = GatewayAgentIdentity.openclaw_agent_id(ctx.gateway)

    token, fatal = await _resolve_agent_auth_token(
        ctx,
        result,
        main_agent,
        board=None,
        agent_gateway_id=main_gateway_agent_id,
    )
    if fatal:
        return True
    if not token:
        _append_sync_error(
            result,
            agent=main_agent,
            message="Skipping gateway agent: unable to read AUTH_TOKEN from TOOLS.md.",
        )
        return True
    stop_sync = False
    try:

        async def _do_provision_main() -> bool:
            await provision_main_agent(
                main_agent,
                MainAgentProvisionRequest(
                    gateway=ctx.gateway,
                    auth_token=token,
                    user=ctx.options.user,
                    session_key=main_session_key,
                    options=ProvisionOptions(
                        action="update",
                        force_bootstrap=ctx.options.force_bootstrap,
                        reset_session=ctx.options.reset_sessions,
                    ),
                ),
            )
            return True

        await _with_gateway_retry(_do_provision_main, backoff=ctx.backoff)
    except TimeoutError as exc:  # pragma: no cover - gateway/network dependent
        _append_sync_error(result, agent=main_agent, message=str(exc))
        stop_sync = True
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        _append_sync_error(
            result,
            agent=main_agent,
            message=f"Failed to sync gateway agent templates: {exc}",
        )
    else:
        result.main_updated = True
    return stop_sync


async def sync_gateway_templates(
    session: AsyncSession,
    gateway: Gateway,
    options: GatewayTemplateSyncOptions,
) -> GatewayTemplatesSyncResult:
    """Synchronize AGENTS/TOOLS/etc templates to gateway-connected agents."""
    result = _base_result(
        gateway,
        include_main=options.include_main,
        reset_sessions=options.reset_sessions,
    )
    if not gateway.url:
        _append_sync_error(
            result,
            message="Gateway URL is not configured for this gateway.",
        )
        return result

    ctx = _SyncContext(
        session=session,
        gateway=gateway,
        config=GatewayClientConfig(url=gateway.url, token=gateway.token),
        backoff=_GatewayBackoff(timeout_s=10 * 60, timeout_context="template sync"),
        options=options,
    )
    if not await _ping_gateway(ctx, result):
        return result

    boards = await Board.objects.filter_by(gateway_id=gateway.id).all(session)
    boards_by_id = _boards_by_id(boards, board_id=options.board_id)
    if boards_by_id is None:
        _append_sync_error(
            result,
            message="Board does not belong to this gateway.",
        )
        return result
    paused_board_ids = await _paused_board_ids(session, list(boards_by_id.keys()))
    if boards_by_id:
        agents = await (
            Agent.objects.by_field_in("board_id", list(boards_by_id.keys()))
            .order_by(col(Agent.created_at).asc())
            .all(session)
        )
    else:
        agents = []

    stop_sync = False
    for agent in agents:
        board = boards_by_id.get(agent.board_id) if agent.board_id is not None else None
        if board is None:
            result.agents_skipped += 1
            _append_sync_error(
                result,
                agent=agent,
                message="Skipping agent: board not found for agent.",
            )
            continue
        if board.id in paused_board_ids:
            result.agents_skipped += 1
            continue
        stop_sync = await _sync_one_agent(ctx, result, agent, board)
        if stop_sync:
            break

    if not stop_sync and options.include_main:
        await _sync_main_agent(ctx, result)
    return result


# Board lead lifecycle primitives consolidated from app.services.board_leads.
def lead_session_key(board: Board) -> str:
    """Return the deterministic main session key for a board lead agent."""
    return f"agent:lead-{board.id}:main"


def lead_agent_name(_: Board) -> str:
    """Return the default display name for board lead agents."""
    return "Lead Agent"


@dataclass(frozen=True, slots=True)
class LeadAgentOptions:
    """Optional overrides for board-lead provisioning behavior."""

    agent_name: str | None = None
    identity_profile: dict[str, str] | None = None
    action: str = "provision"


@dataclass(frozen=True, slots=True)
class LeadAgentRequest:
    """Inputs required to ensure or provision a board lead agent."""

    board: Board
    gateway: Gateway
    config: GatewayClientConfig
    user: User | None
    options: LeadAgentOptions = field(default_factory=LeadAgentOptions)


async def ensure_board_lead_agent(
    session: AsyncSession,
    *,
    request: LeadAgentRequest,
) -> tuple[Agent, bool]:
    """Ensure a board has a lead agent; return `(agent, created)`."""
    board = request.board
    config_options = request.options
    existing = (
        await session.exec(
            select(Agent)
            .where(Agent.board_id == board.id)
            .where(col(Agent.is_board_lead).is_(True)),
        )
    ).first()
    if existing:
        desired_name = config_options.agent_name or lead_agent_name(board)
        changed = False
        if existing.name != desired_name:
            existing.name = desired_name
            changed = True
        if existing.gateway_id != request.gateway.id:
            existing.gateway_id = request.gateway.id
            changed = True
        desired_session_key = lead_session_key(board)
        if not existing.openclaw_session_id:
            existing.openclaw_session_id = desired_session_key
            changed = True
        if changed:
            existing.updated_at = utcnow()
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
        return existing, False

    merged_identity_profile: dict[str, Any] = {
        "role": "Board Lead",
        "communication_style": "direct, concise, practical",
        "emoji": ":gear:",
    }
    if config_options.identity_profile:
        merged_identity_profile.update(
            {
                key: value.strip()
                for key, value in config_options.identity_profile.items()
                if value.strip()
            },
        )

    agent = Agent(
        name=config_options.agent_name or lead_agent_name(board),
        status="provisioning",
        board_id=board.id,
        gateway_id=request.gateway.id,
        is_board_lead=True,
        heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
        identity_profile=merged_identity_profile,
        openclaw_session_id=lead_session_key(board),
        provision_requested_at=utcnow(),
        provision_action=config_options.action,
    )
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    try:
        await provision_agent(
            agent,
            AgentProvisionRequest(
                board=board,
                gateway=request.gateway,
                auth_token=raw_token,
                user=request.user,
                options=ProvisionOptions(action=config_options.action),
            ),
        )
        if agent.openclaw_session_id:
            await ensure_session(
                agent.openclaw_session_id,
                config=request.config,
                label=agent.name,
            )
            await send_message(
                (
                    f"Hello {agent.name}. Your workspace has been provisioned.\n\n"
                    "Start the agent, run BOOT.md, and if BOOTSTRAP.md exists run "
                    "it once then delete it. Begin heartbeats after startup."
                ),
                session_key=agent.openclaw_session_id,
                config=request.config,
                deliver=True,
            )
    except OpenClawGatewayError:
        # Best-effort provisioning. The board/agent rows should still exist.
        pass

    return agent, True
