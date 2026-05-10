# ruff: noqa: INP001
"""Unit tests for board rollout_flags allowlist + unknown capture bucket.

Covers amendment sections A.3 and A.4 from
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
which require:

- known keys go into ``rollout_flags``
- unknown keys go into ``rollout_flags_unknown``
- type validation (reject non-bool values) happens at the Pydantic ingress,
  not in the partition helper

Integration tests for the API PATCH/POST wiring live alongside the other
``test_boards_api*.py`` suites; this file covers the pure partition helper
and the ingress-type validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.boards import (
    ROLLOUT_FLAG_ALLOWLIST,
    BoardUpdate,
    partition_rollout_flags,
)


def test_allowlist_contains_expected_keys() -> None:
    """Sanity check: the canonical allowlist matches the amended plan."""

    assert ROLLOUT_FLAG_ALLOWLIST == frozenset(
        {
            "comment_policy_v1",
            "structured_blockers_v1",
            "operator_decisions_v1",
            "deploy_truth_v1",
            "heartbeat_watchdog_v1",
            "lead_scoring_v1",
            "comment_echo_guard_v1",
        }
    )


def test_partition_empty_input_returns_two_empty_dicts() -> None:
    """Empty / None input must return ({}, {}) without raising."""

    assert partition_rollout_flags({}) == ({}, {})
    assert partition_rollout_flags(None) == ({}, {})


def test_partition_all_known_keys_land_in_first_bucket() -> None:
    """Every known key belongs in the first (known) dict."""

    flags = {key: True for key in ROLLOUT_FLAG_ALLOWLIST}
    known, unknown = partition_rollout_flags(flags)
    assert known == flags
    assert unknown == {}


def test_partition_unknown_keys_land_in_second_bucket() -> None:
    """Unknown keys must be captured, not silently dropped."""

    flags = {"future_phase_vi_v1": True, "operator_only_v42": False}
    known, unknown = partition_rollout_flags(flags)
    assert known == {}
    assert unknown == flags


def test_partition_mixed_input_splits_correctly() -> None:
    """Known + unknown in the same payload must partition cleanly."""

    flags = {
        "comment_policy_v1": True,
        "future_flag_v99": True,
        "heartbeat_watchdog_v1": False,
        "random_key": False,
    }
    known, unknown = partition_rollout_flags(flags)
    assert known == {"comment_policy_v1": True, "heartbeat_watchdog_v1": False}
    assert unknown == {"future_flag_v99": True, "random_key": False}


def test_partition_preserves_false_values() -> None:
    """False is a legal flag state and must survive partitioning."""

    flags = {"comment_policy_v1": False, "future_flag_v9": False}
    known, unknown = partition_rollout_flags(flags)
    assert known == {"comment_policy_v1": False}
    assert unknown == {"future_flag_v9": False}


def test_board_update_rejects_coerced_string_bools() -> None:
    """StrictBool on the ingress schema rejects lax coercion.

    Without ``StrictBool``, Pydantic lax mode coerces ``"true"`` -> True
    and ``"off"`` -> False, so operator typos silently flip flags. The
    amendment requires strict bool; this test pins that.
    """

    for bad_value in ("true", "false", "off", "yes", 1, 0):
        with pytest.raises(ValidationError):
            BoardUpdate(rollout_flags={"comment_policy_v1": bad_value})


def test_board_update_accepts_strict_bools() -> None:
    """Actual bool values pass through BoardUpdate unchanged."""

    update = BoardUpdate(rollout_flags={"comment_policy_v1": True, "heartbeat_watchdog_v1": False})
    assert update.rollout_flags == {
        "comment_policy_v1": True,
        "heartbeat_watchdog_v1": False,
    }


def test_board_update_rejects_none_inside_flag_dict() -> None:
    """``None`` is not a bool and must not sneak through as a flag value."""

    with pytest.raises(ValidationError):
        BoardUpdate(rollout_flags={"comment_policy_v1": None})
