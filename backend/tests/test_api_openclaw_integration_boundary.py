# ruff: noqa: S101
"""Architectural boundary tests for API/OpenClaw integration usage."""

from __future__ import annotations

import re
from pathlib import Path


def test_api_does_not_import_openclaw_gateway_client_directly() -> None:
    """API modules should use OpenClaw services, not integration client imports."""
    repo_root = Path(__file__).resolve().parents[2]
    api_root = repo_root / "backend" / "app" / "api"

    violations: list[str] = []
    for path in api_root.rglob("*.py"):
        rel = path.relative_to(repo_root)
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if line.startswith("from app.integrations.openclaw_gateway import "):
                violations.append(f"{rel}:{lineno}")
            elif line.startswith("import app.integrations.openclaw_gateway"):
                violations.append(f"{rel}:{lineno}")

    assert not violations, (
        "Import OpenClaw integration details via service modules (for example "
        "`app.services.openclaw.shared`) instead of directly from `app.api`. "
        f"Violations: {', '.join(violations)}"
    )


def test_api_uses_safe_gateway_dispatch_helper() -> None:
    """API modules should not call low-level gateway RPC helpers directly."""
    repo_root = Path(__file__).resolve().parents[2]
    api_root = repo_root / "backend" / "app" / "api"

    forbidden = {"ensure_session", "send_message", "openclaw_call"}
    violations: list[str] = []
    for path in api_root.rglob("*.py"):
        rel = path.relative_to(repo_root)
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line.startswith("from app.services.openclaw.gateway_rpc import "):
                continue
            if any(re.search(rf"\\b{name}\\b", line) for name in forbidden):
                violations.append(f"{rel}:{lineno}")

    assert not violations, (
        "Use OpenClaw service modules (for example `app.services.openclaw.gateway_dispatch`) "
        "instead of calling low-level gateway RPC helpers from `app.api`."
        f"Violations: {', '.join(violations)}"
    )
