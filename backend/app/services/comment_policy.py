"""Phase I CommentPolicyService.

Applies the per-board ``comment_signal_filter`` to comment read
statements. Board's rollout_flags gate whether the filter is active at
all; this service is the mechanism, not the switch.

See ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
§1 for filter semantics.

Filter modes:
- ``off``: no filtering. Flagged comments visible to all callers.
  Default for every board until operator explicitly graduates.
- ``default_hidden``: flagged comments hidden by default; any caller
  can pass ``include_flagged=true`` to reveal them.
- ``hidden_strict``: agents never see flagged comments, regardless of
  ``include_flagged``. Non-agent callers (user tokens) CAN reveal via
  ``include_flagged=true``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, or_
from sqlmodel import col

from app.core.logging import get_logger
from app.models.activity_events import ActivityEvent

if TYPE_CHECKING:
    from sqlalchemy.sql.expression import Select

logger = get_logger(__name__)

FILTER_OFF = "off"
FILTER_DEFAULT_HIDDEN = "default_hidden"
FILTER_HIDDEN_STRICT = "hidden_strict"


def _not_flagged_clause() -> ColumnElement[bool]:
    """SQL predicate: the event is unclassified or classified clean.

    NULL means the classifier did not produce an answer (skipped or
    crashed — see ``CommentClassifierResult`` docstring); empty list
    means the classifier ran and found nothing. Both are NOT-flagged.
    Any non-empty list flags the row.

    JSON equality comparison against ``[]`` works on both PostgreSQL
    and SQLite via SQLAlchemy's JSON type.
    """

    return or_(
        col(ActivityEvent.classifier_flags).is_(None),
        col(ActivityEvent.classifier_flags) == [],
    )


def apply_comment_signal_filter(
    statement: "Select",
    *,
    filter_mode: str,
    actor_is_agent: bool,
    include_flagged: bool,
) -> "Select":
    """Apply the board's classifier-filter policy to a comment Select.

    Args:
        statement: the base ``SELECT FROM activity_events WHERE ...``.
        filter_mode: the board's ``comment_signal_filter`` column value.
        actor_is_agent: True for agent-token callers. These are
            subjected to the strictest filter — they never see flagged
            comments in ``hidden_strict`` mode.
        include_flagged: caller-supplied query param. Allows revealing
            flagged rows in modes that normally hide them (subject to
            the actor-type override above).

    Returns:
        The (possibly-filtered) statement. In ``off`` mode, the input
        statement is returned unchanged.
    """

    if filter_mode == FILTER_OFF:
        return statement

    # Strict mode: agents are unconditionally filtered.
    if filter_mode == FILTER_HIDDEN_STRICT and actor_is_agent:
        return statement.where(_not_flagged_clause())

    # default_hidden OR (hidden_strict + non-agent caller): respect
    # include_flagged as an escape hatch.
    if include_flagged:
        return statement

    if filter_mode in {FILTER_DEFAULT_HIDDEN, FILTER_HIDDEN_STRICT}:
        return statement.where(_not_flagged_clause())

    logger.warning(
        "comment_policy.unknown_filter_mode mode=%s — falling back to 'off'",
        filter_mode,
    )
    return statement
