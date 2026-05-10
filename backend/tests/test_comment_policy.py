# ruff: noqa: INP001
"""Unit tests for the Phase I CommentPolicyService.

Covers amendment §1 filter semantics:
- off: no filter, every caller sees everything
- default_hidden: hide flagged unless include_flagged=true
- hidden_strict: agents never see flagged; non-agent + include_flagged
  can reveal

Tests exercise the statement-level predicate (what SQL gets emitted),
not a live DB — inspecting the compiled WHERE clause is enough to pin
the filter's decision tree.
"""

from __future__ import annotations

import pytest
from sqlalchemy import JSON, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.activity_events import ActivityEvent
from app.services.comment_policy import (
    FILTER_DEFAULT_HIDDEN,
    FILTER_HIDDEN_STRICT,
    FILTER_OFF,
    apply_comment_signal_filter,
)


def _base_statement() -> object:
    return select(ActivityEvent).where(ActivityEvent.event_type == "task.comment")


def _where_filters_on_classifier_flags(statement: object) -> bool:
    """True when the statement's WHERE clause references classifier_flags.

    Inspecting ``statement.whereclause`` directly avoids false positives
    from columns mentioned in the SELECT list.
    """

    whereclause = getattr(statement, "whereclause", None)
    if whereclause is None:
        return False
    return "classifier_flags" in str(whereclause)


def test_off_mode_returns_statement_unchanged() -> None:
    """``off`` mode must emit no filter predicate at all."""

    base = _base_statement()
    result = apply_comment_signal_filter(
        base,
        filter_mode=FILTER_OFF,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert not _where_filters_on_classifier_flags(result)


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
            assert not _where_filters_on_classifier_flags(result)


def test_default_hidden_filters_by_default() -> None:
    """``default_hidden`` with include_flagged=false emits the filter."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_DEFAULT_HIDDEN,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert _where_filters_on_classifier_flags(result)


def test_default_hidden_reveals_with_include_flagged() -> None:
    """Any caller can bypass default_hidden with include_flagged=true."""

    for actor_is_agent in (True, False):
        result = apply_comment_signal_filter(
            _base_statement(),
            filter_mode=FILTER_DEFAULT_HIDDEN,
            actor_is_agent=actor_is_agent,
            include_flagged=True,
        )
        assert not _where_filters_on_classifier_flags(result)


def test_hidden_strict_filters_agents_even_with_include_flagged() -> None:
    """Strict mode: agents never see flagged. include_flagged is ignored."""

    for include_flagged in (True, False):
        result = apply_comment_signal_filter(
            _base_statement(),
            filter_mode=FILTER_HIDDEN_STRICT,
            actor_is_agent=True,
            include_flagged=include_flagged,
        )
        assert _where_filters_on_classifier_flags(result)


def test_hidden_strict_allows_non_agent_with_include_flagged() -> None:
    """Strict mode: non-agent callers (user tokens) CAN reveal via include_flagged."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_HIDDEN_STRICT,
        actor_is_agent=False,
        include_flagged=True,
    )
    assert not _where_filters_on_classifier_flags(result)


def test_hidden_strict_filters_non_agent_by_default() -> None:
    """Strict mode default (include_flagged=false): even non-agent hides flagged."""

    result = apply_comment_signal_filter(
        _base_statement(),
        filter_mode=FILTER_HIDDEN_STRICT,
        actor_is_agent=False,
        include_flagged=False,
    )
    assert _where_filters_on_classifier_flags(result)


# --------------------------------------------------------------------
# DB-backed integration tests. These persist ActivityEvent rows with
# every "not flagged" encoding (SQL NULL, legacy JSON-null literal,
# empty list) and one flagged row, then run the filtered SELECT to
# confirm which rows actually survive the WHERE clause — the part the
# clause-inspection tests above cannot cover.
# --------------------------------------------------------------------


async def _seed_events(
    session: AsyncSession,
) -> tuple[ActivityEvent, ActivityEvent, ActivityEvent, ActivityEvent]:
    null_evt = ActivityEvent(event_type="task.comment", classifier_flags=None)
    empty_evt = ActivityEvent(event_type="task.comment", classifier_flags=[])
    flagged_evt = ActivityEvent(event_type="task.comment", classifier_flags=["ack_only"])
    legacy_evt = ActivityEvent(event_type="task.comment", classifier_flags=[])
    session.add_all([null_evt, empty_evt, flagged_evt, legacy_evt])
    await session.commit()
    # Simulate a row written by the pre-fix model (Python None persisted
    # as the JSON ``null`` literal, not SQL NULL). ``JSON.NULL`` is
    # SQLAlchemy's sentinel for exactly that encoding.
    await session.execute(
        update(ActivityEvent)
        .where(ActivityEvent.id == legacy_evt.id)
        .values(classifier_flags=JSON.NULL),
    )
    await session.commit()
    return null_evt, empty_evt, flagged_evt, legacy_evt


@pytest.mark.asyncio
async def test_off_mode_returns_all_rows(sqlite_session: AsyncSession) -> None:
    null_evt, empty_evt, flagged_evt, legacy_evt = await _seed_events(sqlite_session)
    stmt = apply_comment_signal_filter(
        select(ActivityEvent.id),
        filter_mode=FILTER_OFF,
        actor_is_agent=True,
        include_flagged=False,
    )
    ids = set((await sqlite_session.execute(stmt)).scalars().all())
    assert ids == {null_evt.id, empty_evt.id, flagged_evt.id, legacy_evt.id}


@pytest.mark.asyncio
async def test_default_hidden_drops_only_flagged_rows(
    sqlite_session: AsyncSession,
) -> None:
    """All three not-flagged encodings survive; only the populated list is filtered."""

    null_evt, empty_evt, flagged_evt, legacy_evt = await _seed_events(sqlite_session)
    stmt = apply_comment_signal_filter(
        select(ActivityEvent.id),
        filter_mode=FILTER_DEFAULT_HIDDEN,
        actor_is_agent=False,
        include_flagged=False,
    )
    ids = set((await sqlite_session.execute(stmt)).scalars().all())
    assert ids == {null_evt.id, empty_evt.id, legacy_evt.id}
    assert flagged_evt.id not in ids


@pytest.mark.asyncio
async def test_hidden_strict_agent_drops_only_flagged_rows(
    sqlite_session: AsyncSession,
) -> None:
    null_evt, empty_evt, flagged_evt, legacy_evt = await _seed_events(sqlite_session)
    stmt = apply_comment_signal_filter(
        select(ActivityEvent.id),
        filter_mode=FILTER_HIDDEN_STRICT,
        actor_is_agent=True,
        include_flagged=True,
    )
    ids = set((await sqlite_session.execute(stmt)).scalars().all())
    assert ids == {null_evt.id, empty_evt.id, legacy_evt.id}
    assert flagged_evt.id not in ids
