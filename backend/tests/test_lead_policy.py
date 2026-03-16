# ruff: noqa

import hashlib

from app.services.lead_policy import (
    approval_required,
    compute_confidence,
    infer_planning,
    task_fingerprint,
)


def test_compute_confidence_sums_weights():
    rubric = {
        "clarity": 20,
        "constraints": 15,
        "completeness": 10,
        "risk": 20,
        "dependencies": 10,
        "similarity": 5,
    }
    assert compute_confidence(rubric) == 80


def test_approval_required_for_low_confidence():
    assert approval_required(confidence=79, is_external=False, is_risky=False)
    assert not approval_required(confidence=85, is_external=False, is_risky=False)


def test_approval_required_for_external_or_risky():
    assert approval_required(confidence=90, is_external=True, is_risky=False)
    assert approval_required(confidence=90, is_external=False, is_risky=True)


def test_infer_planning_requires_signal_threshold():
    signals = {
        "goal_gap": True,
        "recent_ambiguity": False,
        "research_only": False,
        "stalled_inbox": False,
    }
    assert infer_planning(signals) is False

    signals["recent_ambiguity"] = True
    assert infer_planning(signals) is True


def test_task_fingerprint_deterministic():
    fp1 = task_fingerprint("Title", "Desc", "board-1")
    fp2 = task_fingerprint("Title", "Desc", "board-1")
    assert fp1 == fp2
    assert fp1 == hashlib.sha256("board-1::title::desc".encode()).hexdigest()
