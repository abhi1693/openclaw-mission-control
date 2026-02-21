"""Gateway-only provisioning and lifecycle orchestration.

This module is the low-level layer that talks to the OpenClaw gateway RPC surface.
DB-backed workflows (template sync, lead-agent record creation) live in
`app.services.openclaw.provisioning_db`.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import settings
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services import souls_directory
from app.services.openclaw.constants import (
    BOARD_SHARED_TEMPLATE_MAP,
    DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY,
    DEFAULT_GATEWAY_FILES,
    DEFAULT_HEARTBEAT_CONFIG,
    DEFAULT_IDENTITY_PROFILE,
    EXTRA_IDENTITY_PROFILE_FIELDS,
    HEARTBEAT_AGENT_TEMPLATE,
    HEARTBEAT_LEAD_TEMPLATE,
    IDENTITY_PROFILE_FIELDS,
    LEAD_GATEWAY_FILES,
    LEAD_TEMPLATE_MAP,
    MAIN_TEMPLATE_MAP,
    PRESERVE_AGENT_EDITABLE_FILES,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    ensure_session,
    openclaw_call,
    send_message,
)
from app.services.openclaw.internal.retry import GatewayBackoff
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.internal.agent_key import slugify
from app.services.openclaw.internal.session_keys import (
    board_agent_session_key,
    board_lead_session_key,
)
from app.services.openclaw.shared import GatewayAgentIdentity

if TYPE_CHECKING:
    from app.models.users import User


@dataclass(frozen=True, slots=True)
class ProvisionOptions:
    """Toggles controlling provisioning write/reset behavior."""

    action: str = "provision"
    force_bootstrap: bool = False
    overwrite: bool = False


_ROLE_SOUL_MAX_CHARS = 24_000
_ROLE_SOUL_WORD_RE = re.compile(r"[a-z0-9]+")


def _is_missing_session_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    return any(
        marker in message
        for marker in (
            "not found",
            "unknown session",
            "no such session",
            "session does not exist",
        )
    )


def _is_missing_agent_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    if any(
        marker in message for marker in ("unknown agent", "no such agent", "agent does not exist")
    ):
        return True
    return "agent" in message and "not found" in message


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _templates_root() -> Path:
    return _repo_root() / "templates"


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
    # Backwards-compat: gateway-main agents historically used session keys that encoded
    # "gateway-<id>" while the gateway agent id is "mc-gateway-<id>".
    # Keep the on-disk workspace path stable so existing provisioned files aren't moved.
    if key.startswith("mc-gateway-"):
        key = key.removeprefix("mc-")
    return f"{root}/workspace-{slugify(key)}"


def _email_local_part(email: str) -> str:
    normalized = email.strip()
    if not normalized:
        return ""
    local, _sep, _domain = normalized.partition("@")
    return local.strip() or normalized


def _display_name(user: User | None) -> str:
    if user is None:
        return ""
    name = (user.name or "").strip()
    if name:
        return name
    return (user.email or "").strip()


def _preferred_name(user: User | None) -> str:
    preferred_name = (user.preferred_name or "") if user else ""
    if preferred_name:
        preferred_name = preferred_name.strip().split()[0]
    if preferred_name:
        return preferred_name
    display_name = _display_name(user)
    if display_name:
        if "@" in display_name:
            return _email_local_part(display_name)
        return display_name.split()[0]
    email = (user.email or "") if user else ""
    return _email_local_part(email)


def _user_context(user: User | None) -> dict[str, str]:
    return {
        "user_name": _display_name(user),
        "user_preferred_name": _preferred_name(user),
        "user_pronouns": (user.pronouns or "") if user else "",
        "user_timezone": (user.timezone or "") if user else "",
        "user_notes": (user.notes or "") if user else "",
        "user_context": (user.context or "") if user else "",
    }


def _normalized_identity_profile(agent: Agent) -> dict[str, str]:
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
    return normalized_identity


def _identity_context(agent: Agent) -> dict[str, str]:
    normalized_identity = _normalized_identity_profile(agent)
    identity_context = {
        context_key: normalized_identity.get(field, DEFAULT_IDENTITY_PROFILE[field])
        for field, context_key in IDENTITY_PROFILE_FIELDS.items()
    }
    extra_identity_context = {
        context_key: normalized_identity.get(field, "")
        for field, context_key in EXTRA_IDENTITY_PROFILE_FIELDS.items()
    }
    return {**identity_context, **extra_identity_context}


def _role_slug(role: str) -> str:
    tokens = _ROLE_SOUL_WORD_RE.findall(role.strip().lower())
    return "-".join(tokens)


def _select_role_soul_ref(
    refs: list[souls_directory.SoulRef],
    *,
    role: str,
) -> souls_directory.SoulRef | None:
    role_slug = _role_slug(role)
    if not role_slug:
        return None

    exact_slug = next((ref for ref in refs if ref.slug.lower() == role_slug), None)
    if exact_slug is not None:
        return exact_slug

    prefix_matches = [ref for ref in refs if ref.slug.lower().startswith(f"{role_slug}-")]
    if prefix_matches:
        return sorted(prefix_matches, key=lambda ref: len(ref.slug))[0]

    contains_matches = [ref for ref in refs if role_slug in ref.slug.lower()]
    if contains_matches:
        return sorted(contains_matches, key=lambda ref: len(ref.slug))[0]

    role_tokens = [token for token in role_slug.split("-") if token]
    if len(role_tokens) < 2:
        return None

    scored: list[tuple[int, souls_directory.SoulRef]] = []
    for ref in refs:
        haystack = f"{ref.handle}-{ref.slug}".lower()
        token_hits = sum(1 for token in role_tokens if token in haystack)
        if token_hits >= 2:
            scored.append((token_hits, ref))
    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], len(item[1].slug)))
    return scored[0][1]


async def _resolve_role_soul_markdown(role: str) -> tuple[str, str]:
    if not role.strip():
        return "", ""
    try:
        refs = await souls_directory.list_souls_directory_refs()
        matched_ref = _select_role_soul_ref(refs, role=role)
        if matched_ref is None:
            return "", ""
        content = await souls_directory.fetch_soul_markdown(
            handle=matched_ref.handle,
            slug=matched_ref.slug,
        )
        normalized = content.strip()
        if not normalized:
            return "", ""
        if len(normalized) > _ROLE_SOUL_MAX_CHARS:
            normalized = normalized[:_ROLE_SOUL_MAX_CHARS]
        return normalized, matched_ref.page_url
    except Exception:
        # Best effort only. Provisioning must remain robust even if directory is unavailable.
        return "", ""


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
    identity_context = _identity_context(agent)
    user_context = _user_context(user)
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
        "board_rule_require_approval_for_done": str(board.require_approval_for_done).lower(),
        "board_rule_require_review_before_done": str(board.require_review_before_done).lower(),
        "board_rule_block_status_changes_with_pending_approval": str(
            board.block_status_changes_with_pending_approval
        ).lower(),
        "board_rule_only_lead_can_change_status": str(board.only_lead_can_change_status).lower(),
        "board_rule_max_agents": str(board.max_agents),
        "is_board_lead": str(agent.is_board_lead).lower(),
        "is_main_agent": "false",
        "session_key": session_key,
        "workspace_path": workspace_path,
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": main_session_key,
        "workspace_root": workspace_root,
        **user_context,
        **identity_context,
    }


def _build_main_context(
    agent: Agent,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    base_url = settings.base_url or "REPLACE_WITH_BASE_URL"
    identity_context = _identity_context(agent)
    user_context = _user_context(user)
    return {
        "agent_name": agent.name,
        "agent_id": str(agent.id),
        "is_main_agent": "true",
        "session_key": agent.openclaw_session_id or "",
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": GatewayAgentIdentity.session_key(gateway),
        "workspace_root": gateway.workspace_root or "",
        **user_context,
        **identity_context,
    }


def _session_key(agent: Agent) -> str:
    """Return the deterministic session key for a board-scoped agent.

    Note: Never derive session keys from a human-provided name; use stable ids instead.
    """

    if agent.is_board_lead and agent.board_id is not None:
        return board_lead_session_key(agent.board_id)
    return board_agent_session_key(agent.id)


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
            if not heartbeat_path.exists():
                msg = f"Missing template file: {heartbeat_template}"
                raise FileNotFoundError(msg)
            rendered[name] = env.get_template(heartbeat_template).render(**context).strip()
            continue
        override = overrides.get(name)
        if override:
            rendered[name] = env.from_string(override).render(**context).strip()
            continue
        template_name = (
            template_overrides[name] if template_overrides and name in template_overrides else name
        )
        if template_name == "SOUL.md":
            # Use shared Jinja soul template as the default implementation.
            template_name = "BOARD_SOUL.md.j2"
        path = _templates_root() / template_name
        if not path.exists():
            msg = f"Missing template file: {template_name}"
            raise FileNotFoundError(msg)
        rendered[name] = env.get_template(template_name).render(**context).strip()
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
    async def health(self) -> object:
        raise NotImplementedError

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
    async def list_agent_files(self, agent_id: str) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_agent_file_payload(self, *, agent_id: str, name: str) -> object:
        raise NotImplementedError

    @abstractmethod
    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent_file(self, *, agent_id: str, name: str) -> None:
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

    async def health(self) -> object:
        return await openclaw_call("health", config=self._config)

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

    async def upsert_agent(self, registration: GatewayAgentRegistration) -> None:
        # Prefer an idempotent "create then update" flow.
        # - Avoids enumerating gateway agents for existence checks.
        # - Ensures we always hit the "create" RPC first, per lifecycle expectations.
        try:
            await openclaw_call(
                "agents.create",
                {
                    "name": registration.agent_id,
                    "workspace": registration.workspace_path,
                },
                config=self._config,
            )
        except OpenClawGatewayError as exc:
            message = str(exc).lower()
            if not any(
                marker in message for marker in ("already", "exist", "duplicate", "conflict")
            ):
                raise
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
            if not isinstance(name, str) or not name:
                name = item.get("path")
            if isinstance(name, str) and name:
                index[name] = dict(item)
        return index

    async def get_agent_file_payload(self, *, agent_id: str, name: str) -> object:
        return await openclaw_call(
            "agents.files.get",
            {"agentId": agent_id, "name": name},
            config=self._config,
        )

    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        await openclaw_call(
            "agents.files.set",
            {"agentId": agent_id, "name": name, "content": content},
            config=self._config,
        )

    async def delete_agent_file(self, *, agent_id: str, name: str) -> None:
        await openclaw_call(
            "agents.files.delete",
            {"agentId": agent_id, "name": name},
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

    async def _augment_context(
        self,
        *,
        agent: Agent,
        context: dict[str, str],
    ) -> dict[str, str]:
        _ = agent
        return context

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        return None

    def _file_names(self, agent: Agent) -> set[str]:
        _ = agent
        return set(DEFAULT_GATEWAY_FILES)

    def _preserve_files(self, agent: Agent) -> set[str]:
        _ = agent
        """Files that are expected to evolve inside the agent workspace."""
        return set(PRESERVE_AGENT_EDITABLE_FILES)

    def _allow_stale_file_deletion(self, agent: Agent) -> bool:
        _ = agent
        return False

    def _stale_file_candidates(self, agent: Agent) -> set[str]:
        _ = agent
        return set()

    async def _set_agent_files(
        self,
        *,
        agent: Agent | None = None,
        agent_id: str,
        rendered: dict[str, str],
        desired_file_names: set[str] | None = None,
        existing_files: dict[str, dict[str, Any]],
        action: str,
        overwrite: bool = False,
    ) -> None:
        preserve_files = (
            self._preserve_files(agent) if agent is not None else set(PRESERVE_AGENT_EDITABLE_FILES)
        )
        target_file_names = desired_file_names or set(rendered.keys())
        unsupported_names: list[str] = []

        for name, content in rendered.items():
            if content == "":
                continue
            # Preserve "editable" files only during updates. During first-time provisioning,
            # the gateway may pre-create defaults for USER/MEMORY/etc, and we still want to
            # apply Mission Control's templates.
            if action == "update" and not overwrite and name in preserve_files:
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
                    unsupported_names.append(name)
                    continue
                raise

        if agent is not None and agent.is_board_lead and unsupported_names:
            unsupported_sorted = ", ".join(sorted(set(unsupported_names)))
            msg = (
                "Gateway rejected required lead workspace files as unsupported: "
                f"{unsupported_sorted}"
            )
            raise RuntimeError(msg)

        if agent is None or not self._allow_stale_file_deletion(agent):
            return

        stale_names = (
            set(existing_files.keys()) & self._stale_file_candidates(agent)
        ) - target_file_names
        for name in sorted(stale_names):
            try:
                await self._control_plane.delete_agent_file(agent_id=agent_id, name=name)
            except OpenClawGatewayError as exc:
                message = str(exc).lower()
                if any(
                    marker in message
                    for marker in (
                        "unsupported",
                        "unknown method",
                        "not found",
                        "no such file",
                    )
                ):
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
        # Ensure templates render with the active deterministic session key.
        agent.openclaw_session_id = session_key

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
        context = await self._augment_context(agent=agent, context=context)
        # Always attempt to sync Mission Control's full template set.
        # Do not introspect gateway defaults (avoids touching gateway "main" agent state).
        file_names = self._file_names(agent)
        existing_files = await self._control_plane.list_agent_files(agent_id)
        include_bootstrap = _should_include_bootstrap(
            action=options.action,
            force_bootstrap=options.force_bootstrap,
            existing_files=existing_files,
        )
        rendered = _render_agent_files(
            context,
            agent,
            file_names,
            include_bootstrap=include_bootstrap,
            template_overrides=self._template_overrides(agent),
        )

        await self._set_agent_files(
            agent=agent,
            agent_id=agent_id,
            rendered=rendered,
            desired_file_names=set(rendered.keys()),
            existing_files=existing_files,
            action=options.action,
            overwrite=options.overwrite,
        )


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

    async def _augment_context(
        self,
        *,
        agent: Agent,
        context: dict[str, str],
    ) -> dict[str, str]:
        context = dict(context)
        if agent.is_board_lead:
            context["directory_role_soul_markdown"] = ""
            context["directory_role_soul_source_url"] = ""
            return context

        role = (context.get("identity_role") or "").strip()
        markdown, source_url = await _resolve_role_soul_markdown(role)
        context["directory_role_soul_markdown"] = markdown
        context["directory_role_soul_source_url"] = source_url
        return context

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        overrides = dict(BOARD_SHARED_TEMPLATE_MAP)
        if agent.is_board_lead:
            overrides.update(LEAD_TEMPLATE_MAP)
        return overrides

    def _file_names(self, agent: Agent) -> set[str]:
        if agent.is_board_lead:
            return set(LEAD_GATEWAY_FILES)
        return super()._file_names(agent)

    def _allow_stale_file_deletion(self, agent: Agent) -> bool:
        return bool(agent.is_board_lead)

    def _stale_file_candidates(self, agent: Agent) -> set[str]:
        if not agent.is_board_lead:
            return set()
        return (
            set(DEFAULT_GATEWAY_FILES)
            | set(LEAD_GATEWAY_FILES)
            | {
                "USER.md",
                "ROUTING.md",
                "LEARNINGS.md",
                "ROLE.md",
                "WORKFLOW.md",
                "STATUS.md",
                "APIS.md",
            }
        )


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

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        _ = agent
        return MAIN_TEMPLATE_MAP

    def _preserve_files(self, agent: Agent) -> set[str]:
        _ = agent
        # For gateway-main agents, USER.md is system-managed (derived from org/user context),
        # so keep it in sync even during updates.
        preserved = super()._preserve_files(agent)
        preserved.discard("USER.md")
        return preserved


def _control_plane_for_gateway(gateway: Gateway) -> OpenClawGatewayControlPlane:
    if not gateway.url:
        msg = "Gateway url is required"
        raise OpenClawGatewayError(msg)
    return OpenClawGatewayControlPlane(
        GatewayClientConfig(url=gateway.url, token=gateway.token),
    )


async def _patch_gateway_agent_heartbeats(
    gateway: Gateway,
    *,
    entries: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """Patch multiple agent heartbeat configs in a single gateway config.patch call.

    Each entry is (agent_id, workspace_path, heartbeat_dict).
    """
    control_plane = _control_plane_for_gateway(gateway)
    await control_plane.patch_agent_heartbeats(entries)


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


def _wakeup_text(agent: Agent, *, verb: str) -> str:
    return (
        f"Hello {agent.name}. Your workspace has been {verb}.\n\n"
        "Start the agent. If BOOTSTRAP.md exists, read it first, then read AGENTS.md. "
        "Begin heartbeats after startup."
    )


class OpenClawGatewayProvisioner:
    """Gateway-only agent lifecycle interface (create -> files -> wake)."""

    async def sync_gateway_agent_heartbeats(self, gateway: Gateway, agents: list[Agent]) -> None:
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
        await _patch_gateway_agent_heartbeats(gateway, entries=entries)

    async def apply_agent_lifecycle(
        self,
        *,
        agent: Agent,
        gateway: Gateway,
        board: Board | None,
        auth_token: str,
        user: User | None,
        action: str = "provision",
        force_bootstrap: bool = False,
        overwrite: bool = False,
        reset_session: bool = False,
        wake: bool = True,
        deliver_wakeup: bool = True,
        wakeup_verb: str | None = None,
    ) -> None:
        """Create/update an agent, sync all template files, and optionally wake the agent.

        Lifecycle steps (same for all agent types):
        1) create agent (idempotent)
        2) set/update all template files
        3) wake the agent session (chat.send)
        """

        if not gateway.url:
            msg = "Gateway url is required"
            raise ValueError(msg)

        # Guard against accidental main-agent provisioning without a board.
        if board is None and getattr(agent, "board_id", None) is not None:
            msg = "board is required for board-scoped agent lifecycle"
            raise ValueError(msg)

        # Resolve session key and agent type.
        if board is None:
            session_key = (
                agent.openclaw_session_id or GatewayAgentIdentity.session_key(gateway) or ""
            ).strip()
            if not session_key:
                msg = "gateway main agent session_key is required"
                raise ValueError(msg)
            manager_type: type[BaseAgentLifecycleManager] = GatewayMainAgentLifecycleManager
        else:
            session_key = _session_key(agent)
            manager_type = BoardAgentLifecycleManager

        control_plane = _control_plane_for_gateway(gateway)
        manager = manager_type(gateway, control_plane)
        await manager.provision(
            agent=agent,
            board=board,
            session_key=session_key,
            auth_token=auth_token,
            user=user,
            options=ProvisionOptions(
                action=action,
                force_bootstrap=force_bootstrap,
                overwrite=overwrite,
            ),
            session_label=agent.name or "Gateway Agent",
        )

        client_config = GatewayClientConfig(url=gateway.url, token=gateway.token)
        # Gateway may restart due to config.patch triggered by agents.create above.
        # Use backoff for ALL post-provision gateway calls so we wait for it to come back up.
        _post_provision_backoff = GatewayBackoff(
            timeout_s=45,
            base_delay_s=1.0,
            max_delay_s=10.0,
            timeout_context="post-provision session setup",
        )

        if reset_session:
            async def _reset_with_backoff() -> object:
                try:
                    await control_plane.reset_agent_session(session_key)
                except OpenClawGatewayError as exc:
                    if not _is_missing_session_error(exc):
                        raise
                return True

            await _post_provision_backoff.run(_reset_with_backoff)

        if not wake:
            return

        await _post_provision_backoff.run(
            lambda: ensure_session(session_key, config=client_config, label=agent.name)
        )
        verb = wakeup_verb or ("provisioned" if action == "provision" else "updated")
        await _post_provision_backoff.run(
            lambda: send_message(
                _wakeup_text(agent, verb=verb),
                session_key=session_key,
                config=client_config,
                deliver=deliver_wakeup,
            )
        )

    async def delete_agent_lifecycle(
        self,
        *,
        agent: Agent,
        gateway: Gateway,
        delete_files: bool = True,
        delete_session: bool = True,
    ) -> str | None:
        """Remove agent runtime state from the gateway (agent + optional session)."""

        if not gateway.url:
            msg = "Gateway url is required"
            raise ValueError(msg)
        if not gateway.workspace_root:
            msg = "gateway_workspace_root is required"
            raise ValueError(msg)

        workspace_path = _workspace_path(agent, gateway.workspace_root)
        control_plane = _control_plane_for_gateway(gateway)

        if agent.board_id is None:
            agent_gateway_id = GatewayAgentIdentity.openclaw_agent_id(gateway)
        else:
            agent_gateway_id = _agent_key(agent)
        try:
            await control_plane.delete_agent(agent_gateway_id, delete_files=delete_files)
        except OpenClawGatewayError as exc:
            if not _is_missing_agent_error(exc):
                raise

        if delete_session:
            if agent.board_id is None:
                session_key = (
                    agent.openclaw_session_id or GatewayAgentIdentity.session_key(gateway) or ""
                ).strip()
            else:
                session_key = _session_key(agent)
            if session_key:
                try:
                    await control_plane.delete_agent_session(session_key)
                except OpenClawGatewayError as exc:
                    if not _is_missing_session_error(exc):
                        raise

        return workspace_path
