"""Policy helpers for lead-agent approval and planning decisions."""

from __future__ import annotations

import hashlib
from typing import Mapping

CONFIDENCE_THRESHOLD = 80.0
MIN_PLANNING_SIGNALS = 2


def compute_confidence(rubric_scores: Mapping[str, int]) -> float:
    """Compute aggregate confidence from rubric score components."""
    return float(sum(rubric_scores.values()))


def approval_required(*, confidence: float, is_external: bool, is_risky: bool) -> bool:
    """Return whether an action must go through explicit approval."""
    return is_external or is_risky or confidence < CONFIDENCE_THRESHOLD


def infer_planning(signals: Mapping[str, bool]) -> bool:
    """Infer planning intent from boolean heuristic signals."""
    # Require at least two planning signals to avoid spam on general boards.
    truthy = [key for key, value in signals.items() if value]
    return len(truthy) >= MIN_PLANNING_SIGNALS


def task_fingerprint(title: str, description: str | None, board_id: str) -> str:
    """Build a stable hash key for deduplicating similar board tasks."""
    normalized_title = title.strip().lower()
    normalized_desc = (description or "").strip().lower()
    seed = f"{board_id}::{normalized_title}::{normalized_desc}"
    return hashlib.sha256(seed.encode()).hexdigest()
