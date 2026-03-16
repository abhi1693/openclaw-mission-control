from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.approvals import ApprovalCreate


def test_approval_create_requires_confidence_score() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        ApprovalCreate.model_validate(
            {
                "action_type": "task.update",
                "payload": {"reason": "Missing confidence should fail."},
            },
        )


@pytest.mark.parametrize("confidence", [-1.0, 101.0])
def test_approval_create_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        ApprovalCreate.model_validate(
            {
                "action_type": "task.update",
                "payload": {"reason": "Confidence must be in range."},
                "confidence": confidence,
            },
        )


def test_approval_create_requires_lead_reasoning() -> None:
    with pytest.raises(ValidationError, match="lead reasoning is required"):
        ApprovalCreate.model_validate(
            {
                "action_type": "task.update",
                "confidence": 80,
            },
        )


def test_approval_create_accepts_nested_decision_reason() -> None:
    model = ApprovalCreate.model_validate(
        {
            "action_type": "task.update",
            "confidence": 80,
            "payload": {"decision": {"reason": "Needs manual approval."}},
        },
    )
    assert model.payload == {"decision": {"reason": "Needs manual approval."}}


def test_approval_create_accepts_float_confidence() -> None:
    model = ApprovalCreate.model_validate(
        {
            "action_type": "task.update",
            "confidence": 88.75,
            "payload": {"reason": "Fractional confidence should be preserved."},
        },
    )
    assert model.confidence == 88.75


def test_approval_create_accepts_top_level_lead_reasoning() -> None:
    model = ApprovalCreate.model_validate(
        {
            "action_type": "task.update",
            "confidence": 80,
            "lead_reasoning": "Need manual review before changing task status.",
        },
    )
    assert model.payload == {
        "reason": "Need manual review before changing task status.",
    }
