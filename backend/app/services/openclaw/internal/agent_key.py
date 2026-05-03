"""Agent key derivation helpers shared across OpenClaw modules."""

from __future__ import annotations

import re
from uuid import uuid4

from app.models.agents import Agent
from app.services.openclaw.constants import _SESSION_KEY_PARTS_MIN


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid4().hex


def agent_key(agent: Agent) -> str:
    """Return stable gateway agent id derived from session key or name fallback."""
    session_key = agent.openclaw_session_id or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= _SESSION_KEY_PARTS_MIN and parts[1]:
            return parts[1]
    return slugify(agent.name)


def projection_lookup_id(agent: Agent) -> str | None:
    """Return the gateway agent_id used by the projector for this Agent,
    or ``None`` if the agent has no parseable ``openclaw_session_id``.

    Strict counterpart to :func:`agent_key`. The projector only persists
    rows whose ``sessionKey`` is exactly ``agent:<id>:<label>``
    (3 segments) — see ``parse_session_key`` in
    ``mc_gateway_subscriber.session_state_projector``. ``agent_key``'s
    fallback to ``slugify(agent.name)`` is unsafe for projection
    LOOKUPS: an unprovisioned agent named "QA E2E" would produce
    ``"qa-e2e"`` and silently match a projection row for an UNRELATED
    org's gateway session ``agent:qa-e2e:main``. Use this helper for
    any cross-tenant projection scoping (codex finding 2026-05-03).
    """
    session_key = agent.openclaw_session_id or ""
    if not session_key.startswith("agent:"):
        return None
    parts = session_key.split(":")
    if len(parts) != 3:
        return None
    _, agent_id, label = parts
    if not agent_id or not label:
        return None
    return agent_id
