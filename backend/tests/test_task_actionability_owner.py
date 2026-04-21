# ruff: noqa: INP001
"""Unit tests for Phase IV §I2 owner actionability (plan §I2).

Scope: the new owner check on the pure ``actionability_missing_fields``
helper. End-to-end PATCH coverage rides on the existing
``test_task_agent_permissions.py`` suite, which already exercises the
integrated actionability path.
"""

from __future__ import annotations

from uuid import uuid4

from app.schemas.tasks import (
    OWNER_REQUIRED_STATUSES,
    actionability_missing_fields,
    status_requires_assigned_owner,
)


def _fields(status: str, *, owner: bool) -> list[str]:
    """Call the pure helper with a complete contract triplet so only
    the owner check matters for the assertion."""

    return actionability_missing_fields(
        status=status,
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=uuid4() if owner else None,
    )


def test_owner_required_statuses_are_in_progress_and_done() -> None:
    assert OWNER_REQUIRED_STATUSES == {"in_progress", "done"}


def test_status_requires_assigned_owner_only_fires_for_those() -> None:
    for active in ("in_progress", "done"):
        assert status_requires_assigned_owner(active)
    for passive in ("inbox", "review", "rework", "cancelled", None):
        assert not status_requires_assigned_owner(passive)


def test_owner_missing_flags_in_progress() -> None:
    assert _fields("in_progress", owner=False) == ["assigned_agent_id"]


def test_owner_missing_flags_done() -> None:
    assert _fields("done", owner=False) == ["assigned_agent_id"]


def test_owner_required_but_present_does_not_flag() -> None:
    assert _fields("in_progress", owner=True) == []


def test_review_does_not_require_owner() -> None:
    """Review is a queue state where the reviewer picks up after the
    transition — pre-Phase-IV code explicitly unassigns on entry.
    §I2's owner requirement intentionally carves out this state."""

    assert _fields("review", owner=False) == []


def test_inbox_and_terminal_states_skip_the_check() -> None:
    for status in ("inbox", "cancelled", "rework"):
        assert _fields(status, owner=False) == []


def test_owner_missing_reports_alongside_contract_triplet() -> None:
    """When both owner and triplet are missing, both surface so the
    operator can fix them in one round trip instead of chasing a
    cascade of 409s."""

    result = actionability_missing_fields(
        status="in_progress",
        review_packet_type="frontend_ui",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    )
    assert result == [
        "assigned_agent_id",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    ]
