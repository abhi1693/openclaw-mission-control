from __future__ import annotations

from app.api.board_onboarding import _require_approval_for_done_from_draft


def test_require_approval_for_done_defaults_true_without_lead_agent_draft() -> None:
    assert _require_approval_for_done_from_draft(None) is True
    assert _require_approval_for_done_from_draft({}) is True
    assert _require_approval_for_done_from_draft({"lead_agent": "invalid"}) is True


def test_require_approval_for_done_stays_enabled_for_non_fully_autonomous_modes() -> None:
    assert (
        _require_approval_for_done_from_draft(
            {"lead_agent": {"autonomy_level": "ask_first"}},
        )
        is True
    )
    assert (
        _require_approval_for_done_from_draft(
            {"lead_agent": {"autonomy_level": "balanced"}},
        )
        is True
    )


def test_require_approval_for_done_disables_for_fully_autonomous_choices() -> None:
    assert (
        _require_approval_for_done_from_draft(
            {"lead_agent": {"autonomy_level": "autonomous"}},
        )
        is False
    )
    assert (
        _require_approval_for_done_from_draft(
            {"lead_agent": {"autonomy_level": "fully-autonomous"}},
        )
        is False
    )
    assert (
        _require_approval_for_done_from_draft(
            {"lead_agent": {"identity_profile": {"autonomy_level": "fully autonomous"}}},
        )
        is False
    )
