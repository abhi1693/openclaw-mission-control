from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import tasks as tasks_api
from app.api.tasks import _delivery_contract_incomplete_error
from app.schemas.tasks import (
    OWNER_REQUIRED_STATUSES,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    actionability_missing_fields,
    delivery_contract_missing_fields,
    status_requires_assigned_owner,
)


def test_task_update_accepts_rework_status() -> None:
    model = TaskUpdate(status="rework")
    assert model.status == "rework"


def test_task_update_accepts_cancelled_status() -> None:
    model = TaskUpdate(status="cancelled")
    assert model.status == "cancelled"


def test_status_filter_accepts_rework_and_cancelled() -> None:
    assert tasks_api._status_values("review,rework,cancelled") == [
        "review",
        "rework",
        "cancelled",
    ]


def test_status_filter_rejects_unknown_status() -> None:
    with pytest.raises(HTTPException) as exc:
        tasks_api._status_values("archived")

    assert exc.value.status_code == 422
    assert exc.value.detail == "Unsupported task status filter."


def test_task_create_accepts_control_plane_metadata() -> None:
    model = TaskCreate(
        title="T",
        review_packet_type="frontend_ui",
        validation_target="http://192.168.2.60:3000",
        validation_target_kind="live_url",
        validation_target_scope="review",
        operator_decision_required=True,
        operator_decision_summary="Awaiting operator pricing decision.",
    )
    assert model.review_packet_type == "frontend_ui"
    assert model.validation_target_kind == "live_url"
    assert model.validation_target_scope == "review"
    assert model.operator_decision_required is True


def test_task_update_accepts_control_plane_metadata() -> None:
    model = TaskUpdate(
        review_packet_type="mixed",
        validation_target="/shared/worktree",
        validation_target_kind="workspace",
        validation_target_scope="runtime",
        operator_decision_required=True,
        operator_decision_summary="Awaiting legal text from operator.",
    )
    assert model.review_packet_type == "mixed"
    assert model.validation_target_kind == "workspace"
    assert model.validation_target_scope == "runtime"
    assert model.operator_decision_required is True


def test_task_read_exposes_control_plane_metadata() -> None:
    model = TaskRead(
        id="00000000-0000-4000-8000-000000000001",
        board_id="00000000-0000-4000-8000-000000000002",
        title="T",
        status="inbox",
        priority="medium",
        created_by_user_id=None,
        in_progress_at=None,
        cancelled_at=None,
        created_at="2026-04-16T00:00:00Z",
        updated_at="2026-04-16T00:00:00Z",
        review_packet_type="content_copy",
        validation_target="pricing operator brief",
        validation_target_kind="other",
        validation_target_scope="all",
        operator_decision_required=True,
        operator_decision_summary="Awaiting operator commitments.",
    )
    assert model.review_packet_type == "content_copy"
    assert model.validation_target == "pricing operator brief"
    assert model.operator_decision_required is True


def test_delivery_contract_requires_review_packet_for_active_status() -> None:
    assert delivery_contract_missing_fields(
        status="in_progress",
        review_packet_type=None,
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
    ) == ["review_packet_type"]


def test_delivery_contract_requires_validation_target_for_frontend_review() -> None:
    assert delivery_contract_missing_fields(
        status="review",
        review_packet_type="frontend_ui",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
    ) == [
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    ]


def test_delivery_contract_allows_content_copy_without_validation_target() -> None:
    assert (
        delivery_contract_missing_fields(
            status="review",
            review_packet_type="content_copy",
            validation_target=None,
            validation_target_kind=None,
            validation_target_scope=None,
        )
        == []
    )


# --------------------------------------------------------------------
# Phase IV §I2: actionability owner check (plan reference at
# docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I2).
# --------------------------------------------------------------------


def _actionability(
    status: str, *, owner: bool
) -> list[str]:
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


def test_actionability_owner_missing_flags_in_progress() -> None:
    assert _actionability("in_progress", owner=False) == ["assigned_agent_id"]


def test_actionability_owner_missing_flags_done() -> None:
    assert _actionability("done", owner=False) == ["assigned_agent_id"]


def test_actionability_owner_present_does_not_flag() -> None:
    assert _actionability("in_progress", owner=True) == []


def test_actionability_review_does_not_require_owner() -> None:
    """Review is a queue state where the reviewer picks up after the
    transition — the handler explicitly unassigns on entry. §I2's
    owner requirement intentionally carves out this state."""

    assert _actionability("review", owner=False) == []


def test_actionability_inbox_and_terminal_states_skip_the_check() -> None:
    for status in ("inbox", "cancelled", "rework"):
        assert _actionability(status, owner=False) == []


def test_actionability_reports_owner_alongside_contract_triplet() -> None:
    """When both the owner and the triplet are missing, both surface
    so the operator can fix everything in one round trip."""

    assert actionability_missing_fields(
        status="in_progress",
        review_packet_type="frontend_ui",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == [
        "assigned_agent_id",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    ]


def test_error_message_surfaces_actionability_when_owner_missing() -> None:
    """String-branch coverage: owner-missing tips the message wording
    toward "not actionable" while the wire ``code`` stays stable."""

    exc = _delivery_contract_incomplete_error(
        status_value="in_progress",
        missing_fields=["assigned_agent_id", "validation_target"],
    )
    detail = exc.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "task_delivery_contract_incomplete"
    assert "not actionable" in detail["message"]


def test_error_message_stays_contract_when_owner_present() -> None:
    """Triplet-only violation keeps the legacy wording for
    downstream log-matchers that haven't migrated."""

    exc = _delivery_contract_incomplete_error(
        status_value="review",
        missing_fields=["validation_target"],
    )
    detail = exc.detail
    assert isinstance(detail, dict)
    assert "delivery contract metadata" in detail["message"]
    assert "not actionable" not in detail["message"]


def test_actionability_validates_against_done_when_approval_gates_move_to_done() -> None:
    """move_to_done approval gate must validate against the TARGET
    state (``done``) not the task's current state (``review``).

    Without this, a task whose assignee is cleared between approval
    creation and execution would skip the owner check — ``review``
    doesn't require an owner but ``done`` does, and the lead PATCH
    that actually transitions to ``done`` never re-validates.
    """

    assert actionability_missing_fields(
        status="done",
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == ["assigned_agent_id"]
    # Same payload against the current state ``review`` would NOT
    # flag the owner — the carve-out intentionally skips it.
    assert actionability_missing_fields(
        status="review",
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == []
