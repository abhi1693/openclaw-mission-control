"""Role-based ACP workflow defaults and convergence helpers."""

from __future__ import annotations

from typing import Any

_LEGACY_GENERIC_DEV_ACP_FLOWS = frozenset({"claude_with_skills"})


def desired_dev_acp_flow_for_role(role: str) -> str | None:
    normalized = role.strip().lower()
    if not normalized:
        return None
    if "frontend" in normalized:
        return "claude_then_codex_review"
    if "backend" in normalized:
        return "codex_then_claude_review"
    if "architect" in normalized or "code reviewer" in normalized:
        return "review_only"
    if "devops" in normalized or "infrastructure" in normalized:
        return "claude_with_optional_claude_review"
    return None


def converge_identity_dev_acp_flow(identity_profile: dict[str, Any] | None) -> dict[str, Any] | None:
    profile = dict(identity_profile) if isinstance(identity_profile, dict) else {}
    role = str(profile.get("role") or "").strip()
    desired = desired_dev_acp_flow_for_role(role)
    if not desired:
        return None
    current = str(profile.get("dev_acp_flow") or "").strip()
    if current == desired:
        return None
    if current and current not in _LEGACY_GENERIC_DEV_ACP_FLOWS:
        return None
    profile["dev_acp_flow"] = desired
    return profile
