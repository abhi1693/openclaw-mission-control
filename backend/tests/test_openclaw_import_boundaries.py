# ruff: noqa: S101
"""Architectural boundary tests for OpenClaw service imports."""

from __future__ import annotations

from pathlib import Path


def test_no_openclaw_package_barrel_imports() -> None:
    """Disallow `from app.services.openclaw import ...` in backend code."""
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    scan_roots = (backend_root / "app", backend_root / "tests")

    violations: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(repo_root)
            for lineno, raw_line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                line = raw_line.strip()
                if line.startswith("from app.services.openclaw import "):
                    violations.append(f"{rel}:{lineno}")

    assert not violations, (
        "Use concrete OpenClaw modules (for example "
        "`from app.services.openclaw.provisioning_db import ...`) instead of package imports. "
        f"Violations: {', '.join(violations)}"
    )
