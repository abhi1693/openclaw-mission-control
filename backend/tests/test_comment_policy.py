# ruff: noqa: INP001
"""Unit tests for the Phase I CommentPolicyService.

Covers amendment §1 filter semantics:
- off: no filter, every caller sees everything
- default_hidden: hide flagged unless include_flagged=true
- hidden_strict: agents never see flagged; non-agent + include_flagged
  can reveal

Tests exercise the statement-level predicate (what SQL gets emitted),
not a live DB — the compiled SQL fragment is enough to pin the
filter's decision tree.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.activity_events import ActivityEvent
from app.services.comment_policy import (
    FILTER_DEFAULT_HIDDEN,
    FILTER_HIDDEN_STRICT,
    FILTER_OFF,
    apply_comment_signal_filter,
)


def _base_statement() -> object:
    return select(ActivityEvent).where(
        ActivityEvent.event_type == "task.comment"
    )


def _sql_contains_not_flagged_predicate(statement: object) -> bool:
    """True when the WHERE clause contains the classifier_flags filter.

    The SELECT clause always mentions ``classifier_flags`` as a column,
    so we have to inspect the WHERE predicate specifically — counting
    occurrences of "classifier_flags" and treating ≥2 as "also in the
    WHERE clause". The hard-case is that a filtered select has one
    mention in the SELECT list AND one in the WHERE.
    """

    rendered = str(statement).lower()
    return rendered.count("classifier_flags") >= 2


def test_off_mode_returns_statement_unchanged() -> None:
    """``off`` mode must emit no filter predicate at all."""

    base = _base_statement()
    result = apply_comment_signal_filter(
        base,
        filter_mode=FILTER_OFF,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert not _sql_contains_not_flagged_predicate(result)


def test_off_mode_ignores_include_flagged_and_actor() -> None:
    """``off`` doesn't care about the other params."""

    base = _base_statement()
    for actor_is_agent in (True, False):
        for include_flagged in (True, False):
            result = apply_comment_signal_filter(
                base,
                filter_mode=FILTER_OFF,
                actor_is_agent=actor_is_agent,
                include_flagged=include_flagged,
            )
            assert not _sql_contains_not_flagged_predicate(result)


def test_default_hidden_filters_by_default() -> None:
    """``default_hidden`` with include_flagged=false emits the filter."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_DEFAULT_HIDDEN,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert _sql_contains_not_flagged_predicate(result)


def test_default_hidden_reveals_with_include_flagged() -> None:
    """Any caller can bypass default_hidden with include_flagged=true."""

    for actor_is_agent in (True, False):
        result = apply_comment_signal_filter(
            _base_statement(),
            filter_mode=FILTER_DEFAULT_HIDDEN,
            actor_is_agent=actor_is_agent,
            include_flagged=True,
        )
        assert not _sql_contains_not_flagged_predicate(result)


def test_hidden_strict_filters_agents_even_with_include_flagged() -> None:
    """Strict mode: agents never see flagged. include_flagged is ignored."""

    for include_flagged in (True, False):
        result = apply_comment_signal_filter(
            _base_statement(),
            filter_mode=FILTER_HIDDEN_STRICT,
            actor_is_agent=True,
            include_flagged=include_flagged,
        )
        assert _sql_contains_not_flagged_predicate(result)


def test_hidden_strict_allows_non_agent_with_include_flagged() -> None:
    """Strict mode: non-agent callers (user tokens) CAN reveal via include_flagged."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_HIDDEN_STRICT,
        actor_is_agent=False,
        include_flagged=True,
    )
    assert not _sql_contains_not_flagged_predicate(result)


def test_hidden_strict_filters_non_agent_by_default() -> None:
    """Strict mode default (include_flagged=false): even non-agent hides flagged."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_HIDDEN_STRICT,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert _sql_contains_not_flagged_predicate(result)


def test_unknown_mode_falls_back_to_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown mode values (someone wrote 'hidden' instead of 'hidden_strict')
    fall back to 'off' with a WARN log, not a crash."""

    with caplog.at_level("WARNING", logger="app.services.comment_policy"):
        result = apply_comment_signal_filter(
            _base_statement(),
            filter_mode="bogus_mode",
            actor_is_agent=False,
            include_flagged=False,
        )
    assert not _sql_contains_not_flagged_predicate(result)
    assert "unknown_filter_mode" in caplog.text
