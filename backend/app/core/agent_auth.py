"""Agent authentication helpers for token-backed API access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from fastapi import Depends, Header, HTTPException, Request, status
from sqlmodel import col, select

from app.core.agent_tokens import verify_agent_token
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.agents import Agent

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

_LAST_SEEN_TOUCH_INTERVAL = timedelta(seconds=30)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_DEP = Depends(get_session)


@dataclass
class AgentAuthContext:
    """Authenticated actor payload for agent-originated requests."""

    actor_type: Literal["agent"]
    agent: Agent


async def _find_agent_for_token(session: AsyncSession, token: str) -> Agent | None:
    agents = list(
        await session.exec(
            select(Agent).where(col(Agent.agent_token_hash).is_not(None)),
        ),
    )
    for agent in agents:
        if agent.agent_token_hash and verify_agent_token(token, agent.agent_token_hash):
            return agent
    return None


def _resolve_agent_token(
    agent_token: str | None,
    authorization: str | None,
    *,
    accept_authorization: bool = True,
) -> str | None:
    if agent_token:
        return agent_token
    if not accept_authorization:
        return None
    if not authorization:
        return None
    value = authorization.strip()
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip() or None
    return None


async def _touch_agent_presence(
    request: Request,
    session: AsyncSession,
    agent: Agent,
) -> None:
    """Best-effort update of last_seen/status for any authenticated agent request.

    Heartbeats are the primary presence mechanism, but agents may still make API
    calls (task comments, memory updates, etc). Touch presence so the UI reflects
    real activity even if the heartbeat loop isn't running.
    """
    now = utcnow()
    if agent.last_seen_at is not None and now - agent.last_seen_at < _LAST_SEEN_TOUCH_INTERVAL:
        return

    agent.last_seen_at = now
    agent.updated_at = now
    if agent.status not in {"updating", "deleting"}:
        agent.status = "online"
    session.add(agent)

    # For safe HTTP methods, endpoints typically do not commit. Persist the touch
    # so agents that only poll/read still show as online.
    if request.method.upper() in _SAFE_METHODS:
        await session.commit()


async def get_agent_auth_context(
    request: Request,
    agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = SESSION_DEP,
) -> AgentAuthContext:
    """Require and validate agent auth token from request headers."""
    resolved = _resolve_agent_token(
        agent_token,
        authorization,
        accept_authorization=True,
    )
    if not resolved:
        logger.warning(
            "agent auth missing token path=%s x_agent=%s authorization=%s",
            request.url.path,
            bool(agent_token),
            bool(authorization),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    agent = await _find_agent_for_token(session, resolved)
    if agent is None:
        logger.warning(
            "agent auth invalid token path=%s token_prefix=%s",
            request.url.path,
            resolved[:6],
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await _touch_agent_presence(request, session, agent)
    return AgentAuthContext(actor_type="agent", agent=agent)


async def get_agent_auth_context_optional(
    request: Request,
    agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = SESSION_DEP,
) -> AgentAuthContext | None:
    """Optionally resolve agent auth context from `X-Agent-Token` only."""
    resolved = _resolve_agent_token(
        agent_token,
        authorization,
        accept_authorization=False,
    )
    if not resolved:
        if agent_token:
            logger.warning(
                "agent auth optional missing token path=%s x_agent=%s authorization=%s",
                request.url.path,
                bool(agent_token),
                bool(authorization),
            )
        return None
    agent = await _find_agent_for_token(session, resolved)
    if agent is None:
        logger.warning(
            "agent auth optional invalid token path=%s token_prefix=%s",
            request.url.path,
            resolved[:6],
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await _touch_agent_presence(request, session, agent)
    return AgentAuthContext(actor_type="agent", agent=agent)
