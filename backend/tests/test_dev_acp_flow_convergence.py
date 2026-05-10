from __future__ import annotations

from app.services.openclaw.acp_policy import (
    converge_identity_dev_acp_flow,
    desired_dev_acp_flow_for_role,
)


def _profile(role: str, flow: str | None = None) -> dict[str, str]:
    profile = {"role": role}
    if flow is not None:
        profile["dev_acp_flow"] = flow
    return profile


def test_role_default_mapping_is_deterministic() -> None:
    assert desired_dev_acp_flow_for_role("Backend Developer") == "codex_then_claude_review"
    assert desired_dev_acp_flow_for_role("Frontend Developer") == "claude_then_codex_review"
    assert desired_dev_acp_flow_for_role("System Architect and Code Reviewer") == "review_only"
    assert desired_dev_acp_flow_for_role("DevOps Engineer") == "claude_with_optional_claude_review"


def test_converges_missing_frontend_flow() -> None:
    profile = _profile("Frontend Developer")

    changed = converge_identity_dev_acp_flow(profile)

    assert changed == {
        "role": "Frontend Developer",
        "dev_acp_flow": "claude_then_codex_review",
    }


def test_converges_legacy_frontend_flow() -> None:
    profile = _profile("Frontend Developer", "claude_with_skills")

    changed = converge_identity_dev_acp_flow(profile)

    assert changed == {
        "role": "Frontend Developer",
        "dev_acp_flow": "claude_then_codex_review",
    }


def test_preserves_explicit_custom_flow() -> None:
    profile = _profile("Frontend Developer", "review_only")

    changed = converge_identity_dev_acp_flow(profile)

    assert changed is None
