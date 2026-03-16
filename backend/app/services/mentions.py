"""Helpers for extracting and matching `@mention` tokens in text."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.models.agents import Agent

# Mention tokens are single, space-free words (e.g. "@alex", "@lead").
MENTION_PATTERN = re.compile(r"@([A-Za-z][\w-]{0,31})")


def extract_mentions(message: str) -> set[str]:
    """Extract normalized mention handles from a message body."""
    return {match.group(1).lower() for match in MENTION_PATTERN.finditer(message)}


def matches_agent_mention(agent: Agent, mentions: set[str]) -> bool:
    """Return whether a mention set targets the provided agent."""
    if not mentions:
        return False

    # "@lead" is a reserved shortcut that always targets the board lead.
    if "lead" in mentions and agent.is_board_lead:
        return True
    mentions = mentions - {"lead"}

    name = (agent.name or "").strip()
    if not name:
        return False

    normalized = name.lower()
    if normalized in mentions:
        return True

    # Mentions are single tokens; match on first name for display names with spaces.
    first = normalized.split()[0]
    return first in mentions
