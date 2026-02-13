# ruff: noqa: INP001
"""Schema validation tests for board and onboarding goal requirements."""

from uuid import uuid4

import pytest

from app.schemas.board_onboarding import BoardOnboardingConfirm
from app.schemas.boards import BoardCreate, BoardUpdate


def test_goal_board_requires_objective_and_metrics_when_confirmed() -> None:
    """Confirmed goal boards should require objective and success metrics."""
    with pytest.raises(
        ValueError,
        match="Confirmed goal boards require objective and success_metrics",
    ):
        BoardCreate(
            name="Goal Board",
            slug="goal",
            description="Ship onboarding improvements.",
            gateway_id=uuid4(),
            board_type="goal",
            goal_confirmed=True,
        )

    BoardCreate(
        name="Goal Board",
        slug="goal",
        description="Ship onboarding improvements.",
        gateway_id=uuid4(),
        board_type="goal",
        goal_confirmed=True,
        objective="Launch onboarding",
        success_metrics={"emails": 3},
    )


def test_goal_board_allows_missing_objective_before_confirmation() -> None:
    """Draft goal boards may omit objective/success_metrics before confirmation."""
    BoardCreate(
        name="Draft",
        slug="draft",
        description="Iterate on backlog hygiene.",
        gateway_id=uuid4(),
        board_type="goal",
    )


def test_general_board_allows_missing_objective() -> None:
    """General boards should allow missing goal-specific fields."""
    BoardCreate(
        name="General",
        slug="general",
        description="General coordination board.",
        gateway_id=uuid4(),
        board_type="general",
    )


def test_board_create_requires_description() -> None:
    """Board creation should reject empty descriptions."""
    with pytest.raises(ValueError, match="description is required"):
        BoardCreate(
            name="Goal Board",
            slug="goal",
            description="  ",
            gateway_id=uuid4(),
            board_type="goal",
        )


def test_board_update_rejects_empty_description_patch() -> None:
    """Patch payloads should reject blank descriptions."""
    with pytest.raises(ValueError, match="description is required"):
        BoardUpdate(description="   ")


def test_board_rule_toggles_have_expected_defaults() -> None:
    """Boards should default to approval-gated done and optional review gating."""
    created = BoardCreate(
        name="Ops Board",
        slug="ops-board",
        description="Operations workflow board.",
        gateway_id=uuid4(),
    )
    assert created.require_approval_for_done is True
    assert created.require_review_before_done is False
    assert created.block_status_changes_with_pending_approval is False
    assert created.only_lead_can_change_status is False

    updated = BoardUpdate(
        require_approval_for_done=False,
        require_review_before_done=True,
        block_status_changes_with_pending_approval=True,
        only_lead_can_change_status=True,
    )
    assert updated.require_approval_for_done is False
    assert updated.require_review_before_done is True
    assert updated.block_status_changes_with_pending_approval is True
    assert updated.only_lead_can_change_status is True


def test_onboarding_confirm_requires_goal_fields() -> None:
    """Onboarding confirm should enforce goal fields for goal board types."""
    with pytest.raises(
        ValueError,
        match="Confirmed goal boards require objective and success_metrics",
    ):
        BoardOnboardingConfirm(board_type="goal")

    with pytest.raises(
        ValueError,
        match="Confirmed goal boards require objective and success_metrics",
    ):
        BoardOnboardingConfirm(board_type="goal", objective="Ship onboarding")

    with pytest.raises(
        ValueError,
        match="Confirmed goal boards require objective and success_metrics",
    ):
        BoardOnboardingConfirm(board_type="goal", success_metrics={"emails": 3})

    BoardOnboardingConfirm(
        board_type="goal",
        objective="Ship onboarding",
        success_metrics={"emails": 3},
    )

    BoardOnboardingConfirm(board_type="general")
