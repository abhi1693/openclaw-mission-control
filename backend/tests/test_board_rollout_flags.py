# ruff: noqa: INP001
"""Unit tests for board rollout_flags allowlist + unknown capture bucket.

Covers amendment sections A.3 and A.4 from
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
which require:

- known keys go into ``rollout_flags``
- unknown keys go into ``rollout_flags_unknown``
- non-boolean values are dropped silently (type coercion not implicit)
- empty / None input produces two empty dicts

Integration tests for the API PATCH/POST wiring live alongside the other
``test_boards_api*.py`` suites; this file covers the pure partition helper.
"""

from __future__ import annotations

from app.schemas.boards import (
    ROLLOUT_FLAG_ALLOWLIST,
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


def test_partition_drops_non_boolean_values() -> None:
    """Rollout flags are strictly boolean — strings/ints/lists are dropped."""

    flags = {
        "comment_policy_v1": True,
        "structured_blockers_v1": "true",  # str, not bool -> dropped
        "operator_decisions_v1": 1,  # int, not bool -> dropped
        "deploy_truth_v1": None,  # None, not bool -> dropped
        "unknown_but_bool": True,
    }
    known, unknown = partition_rollout_flags(flags)
    assert known == {"comment_policy_v1": True}
    assert unknown == {"unknown_but_bool": True}


def test_partition_preserves_false_values() -> None:
    """False is a legal flag state and must survive partitioning."""

    flags = {"comment_policy_v1": False, "future_flag_v9": False}
    known, unknown = partition_rollout_flags(flags)
    assert known == {"comment_policy_v1": False}
    assert unknown == {"future_flag_v9": False}
