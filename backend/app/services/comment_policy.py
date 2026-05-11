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

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ColumnElement, or_
from sqlmodel import col

from app.models.activity_events import ActivityEvent
from app.schemas.boards import CommentSignalFilter

if TYPE_CHECKING:
    from sqlmodel.sql.expression import Select, SelectOfScalar

FILTER_OFF: CommentSignalFilter = "off"
FILTER_DEFAULT_HIDDEN: CommentSignalFilter = "default_hidden"
FILTER_HIDDEN_STRICT: CommentSignalFilter = "hidden_strict"


def _not_flagged_clause() -> ColumnElement[bool]:
    """SQL predicate: the event is unclassified or classified clean.

    Three equivalent "not flagged" shapes:
    - SQL NULL (classifier skipped/crashed; the preferred encoding now
      that the column uses ``JSON(none_as_null=True)``);
    - JSON ``null`` literal (legacy rows written before the model fix —
      the plain JSON type serialised Python ``None`` as JSON ``"null"``);
    - JSON empty array (classifier ran and found nothing).

    Any non-empty list flags the row.
    """

    return or_(
        col(ActivityEvent.classifier_flags).is_(None),
        col(ActivityEvent.classifier_flags) == JSON.NULL,
        col(ActivityEvent.classifier_flags) == [],
    )


def apply_comment_signal_filter(
    statement: "Select[Any] | SelectOfScalar[Any]",
    *,
    filter_mode: CommentSignalFilter,
    actor_is_agent: bool,
    include_flagged: bool,
) -> "Select[Any] | SelectOfScalar[Any]":
    """Apply the board's classifier-filter policy to a comment Select.

    Args:
        statement: the base ``SELECT FROM activity_events WHERE ...``.
        filter_mode: the board's ``comment_signal_filter`` column value.
            The DB CHECK constraint + Pydantic Literal guarantee this is
            one of the three canonical values.
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

    if filter_mode == FILTER_HIDDEN_STRICT and actor_is_agent:
        return statement.where(_not_flagged_clause())

    if include_flagged:
        return statement

    return statement.where(_not_flagged_clause())
