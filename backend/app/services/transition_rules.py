"""Tag-based status transition rules for board tasks.

Rules apply when a task has one or more "controlled" tags.
Tasks without controlled tags allow free status transitions.

Controlled tags (by slug):
  - feature, enhancement, bug, document

Transition map (forward-sequential + reset-to-inbox from any non-done state):
  inbox → todo
  todo → in_progress | inbox
  in_progress → in_review | inbox
  in_review → sprint_done | inbox
  sprint_done → done | inbox
  done → (terminal — requires approval, no further transitions)
"""

from __future__ import annotations

# Tag slugs that trigger sequential transition enforcement.
CONTROLLED_TAG_SLUGS: frozenset[str] = frozenset(
    {"feature", "enhancement", "bug", "document"}
)

# Allowed next statuses for each current status.
# "inbox" is always allowed as a reset/rework target from non-done states.
TRANSITION_MAP: dict[str, list[str]] = {
    "inbox": ["todo"],
    "todo": ["in_progress", "inbox"],
    "in_progress": ["in_review", "inbox"],
    "in_review": ["sprint_done", "inbox"],
    "sprint_done": ["done", "inbox"],
    "done": [],
}


def has_controlled_tags(tag_slugs: set[str]) -> bool:
    """Return True if any tag slug is in the controlled set."""
    return bool(tag_slugs & CONTROLLED_TAG_SLUGS)


def get_allowed_transitions(current_status: str) -> list[str]:
    """Return the list of allowed next statuses from the given status.

    Returns an empty list for unknown statuses (treated as terminal).
    """
    return list(TRANSITION_MAP.get(current_status, []))


def is_valid_transition(current_status: str, target_status: str) -> bool:
    """Return True if transitioning from current_status to target_status is allowed."""
    # No-op is always valid.
    if current_status == target_status:
        return True
    return target_status in TRANSITION_MAP.get(current_status, [])
