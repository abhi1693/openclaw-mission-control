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
