from __future__ import annotations

import re
from uuid import UUID, uuid4

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.agent_tokens import generate_agent_token, hash_agent_token, verify_agent_token
from app.core.time import utcnow
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, openclaw_call
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.users import User
from app.schemas.gateways import GatewayTemplatesSyncError, GatewayTemplatesSyncResult
from app.services.agent_provisioning import provision_agent, provision_main_agent

_TOOLS_KV_RE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def _gateway_agent_id(agent: Agent) -> str:
    session_key = agent.openclaw_session_id or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return _slugify(agent.name)


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
) -> str | None:
    try:
        payload = await openclaw_call(
            "agents.files.get",
            {"agentId": agent_gateway_id, "name": name},
            config=config,
        )
    except OpenClawGatewayError:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        # Common shapes:
        # - {"name": "...", "content": "..."}
        # - {"file": {"name": "...", "content": "..." }}
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
) -> str | None:
    tools = await _get_agent_file(agent_gateway_id=agent_gateway_id, name="TOOLS.md", config=config)
    if not tools:
        return None
    values = _parse_tools_md(tools)
    token = values.get("AUTH_TOKEN")
    if not token:
        return None
    token = token.strip()
    return token or None


async def _gateway_default_agent_id(config: GatewayClientConfig) -> str | None:
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


async def sync_gateway_templates(
    session: AsyncSession,
    gateway: Gateway,
    *,
    user: User | None,
    include_main: bool = True,
    reset_sessions: bool = False,
    rotate_tokens: bool = False,
    force_bootstrap: bool = False,
    board_id: UUID | None = None,
) -> GatewayTemplatesSyncResult:
    result = GatewayTemplatesSyncResult(
        gateway_id=gateway.id,
        include_main=include_main,
        reset_sessions=reset_sessions,
        agents_updated=0,
        agents_skipped=0,
        main_updated=False,
    )
    if not gateway.url:
        result.errors.append(
            GatewayTemplatesSyncError(message="Gateway URL is not configured for this gateway.")
        )
        return result

    client_config = GatewayClientConfig(url=gateway.url, token=gateway.token)

    boards = list(await session.exec(select(Board).where(col(Board.gateway_id) == gateway.id)))
    boards_by_id = {board.id: board for board in boards}
    if board_id is not None:
        board = boards_by_id.get(board_id)
        if board is None:
            result.errors.append(
                GatewayTemplatesSyncError(
                    board_id=board_id,
                    message="Board does not belong to this gateway.",
                )
            )
            return result
        boards_by_id = {board_id: board}

    if boards_by_id:
        agents = list(
            await session.exec(
                select(Agent)
                .where(col(Agent.board_id).in_(list(boards_by_id.keys())))
                .order_by(col(Agent.created_at).asc())
            )
        )
    else:
        agents = []

    for agent in agents:
        board = boards_by_id.get(agent.board_id) if agent.board_id is not None else None
        if board is None:
            result.agents_skipped += 1
            result.errors.append(
                GatewayTemplatesSyncError(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    board_id=agent.board_id,
                    message="Skipping agent: board not found for agent.",
                )
            )
            continue

        agent_gateway_id = _gateway_agent_id(agent)
        auth_token = await _get_existing_auth_token(
            agent_gateway_id=agent_gateway_id, config=client_config
        )

        if not auth_token:
            if not rotate_tokens:
                result.agents_skipped += 1
                result.errors.append(
                    GatewayTemplatesSyncError(
                        agent_id=agent.id,
                        agent_name=agent.name,
                        board_id=board.id,
                        message="Skipping agent: unable to read AUTH_TOKEN from TOOLS.md (run with rotate_tokens=true to re-key).",
                    )
                )
                continue
            raw_token = generate_agent_token()
            agent.agent_token_hash = hash_agent_token(raw_token)
            agent.updated_at = utcnow()
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
            auth_token = raw_token

        if agent.agent_token_hash and not verify_agent_token(auth_token, agent.agent_token_hash):
            # Do not block template sync on token drift; optionally re-key.
            if rotate_tokens:
                raw_token = generate_agent_token()
                agent.agent_token_hash = hash_agent_token(raw_token)
                agent.updated_at = utcnow()
                session.add(agent)
                await session.commit()
                await session.refresh(agent)
                auth_token = raw_token
            else:
                result.errors.append(
                    GatewayTemplatesSyncError(
                        agent_id=agent.id,
                        agent_name=agent.name,
                        board_id=board.id,
                        message="Warning: AUTH_TOKEN in TOOLS.md does not match backend token hash (agent auth may be broken).",
                    )
                )

        try:
            await provision_agent(
                agent,
                board,
                gateway,
                auth_token,
                user,
                action="update",
                force_bootstrap=force_bootstrap,
                reset_session=reset_sessions,
            )
            result.agents_updated += 1
        except Exception as exc:  # pragma: no cover - gateway/network dependent
            result.agents_skipped += 1
            result.errors.append(
                GatewayTemplatesSyncError(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    board_id=board.id,
                    message=f"Failed to sync templates: {exc}",
                )
            )

    if include_main:
        main_agent = (
            await session.exec(
                select(Agent).where(col(Agent.openclaw_session_id) == gateway.main_session_key)
            )
        ).first()
        if main_agent is None:
            result.errors.append(
                GatewayTemplatesSyncError(
                    message="Gateway main agent record not found; skipping main agent template sync.",
                )
            )
            return result

        main_gateway_agent_id = await _gateway_default_agent_id(client_config)
        if not main_gateway_agent_id:
            result.errors.append(
                GatewayTemplatesSyncError(
                    agent_id=main_agent.id,
                    agent_name=main_agent.name,
                    message="Unable to resolve gateway default agent id for main agent.",
                )
            )
            return result

        main_token = await _get_existing_auth_token(
            agent_gateway_id=main_gateway_agent_id, config=client_config
        )
        if not main_token:
            result.errors.append(
                GatewayTemplatesSyncError(
                    agent_id=main_agent.id,
                    agent_name=main_agent.name,
                    message="Skipping main agent: unable to read AUTH_TOKEN from TOOLS.md.",
                )
            )
            return result

        try:
            await provision_main_agent(
                main_agent,
                gateway,
                main_token,
                user,
                action="update",
                force_bootstrap=force_bootstrap,
                reset_session=reset_sessions,
            )
            result.main_updated = True
        except Exception as exc:  # pragma: no cover - gateway/network dependent
            result.errors.append(
                GatewayTemplatesSyncError(
                    agent_id=main_agent.id,
                    agent_name=main_agent.name,
                    message=f"Failed to sync main agent templates: {exc}",
                )
            )

    return result
