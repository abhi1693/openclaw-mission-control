"""Offline tests for the agent workspace drift checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_agent_workspace_drift.py"
_spec = importlib.util.spec_from_file_location("check_agent_workspace_drift", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_workspace_drift"] = _module
_spec.loader.exec_module(_module)

compare_skill_roots = _module.compare_skill_roots
compare_template_pairs = _module.compare_template_pairs
has_drift = _module.has_drift


def test_compare_skill_roots_reports_missing_and_changed_skills(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    active = tmp_path / "active"
    (canonical / "lead-next-action-gate").mkdir(parents=True)
    (canonical / "lead-inbox-routing").mkdir(parents=True)
    (active / "lead-next-action-gate").mkdir(parents=True)

    (canonical / "lead-next-action-gate" / "SKILL.md").write_text(
        "canonical action mapping\n",
        encoding="utf-8",
    )
    (canonical / "lead-inbox-routing" / "SKILL.md").write_text(
        "canonical inbox routing\n",
        encoding="utf-8",
    )
    (active / "lead-next-action-gate" / "SKILL.md").write_text(
        "stale action mapping\n",
        encoding="utf-8",
    )

    records = compare_skill_roots(canonical, active)

    by_path = {record.rel_path: record for record in records}
    assert by_path["skills/lead-next-action-gate/SKILL.md"].status == "changed"
    assert by_path["skills/lead-inbox-routing/SKILL.md"].status == "missing"
    assert has_drift(records)


def test_compare_skill_roots_reports_requested_unknown_skill(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    active = tmp_path / "active"
    canonical.mkdir()
    active.mkdir()

    records = compare_skill_roots(
        canonical,
        active,
        skill_names={"missing-skill"},
    )

    assert len(records) == 1
    assert records[0].rel_path == "skills/missing-skill/SKILL.md"
    assert records[0].status == "missing_canonical"
    assert has_drift(records)


def test_compare_template_pairs_renders_expected_template_text(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    workspace = tmp_path / "workspace"
    templates.mkdir()
    workspace.mkdir()
    (templates / "BOARD_HEARTBEAT.md.j2").write_text(
        "heartbeat for {{ agent_name }}\n",
        encoding="utf-8",
    )
    (workspace / "HEARTBEAT.md").write_text(
        "heartbeat for old-agent\n",
        encoding="utf-8",
    )

    records = compare_template_pairs(
        templates_root=templates,
        workspace_root=workspace,
        context={"agent_name": "Supervisor"},
        pairs=[("BOARD_HEARTBEAT.md.j2", "HEARTBEAT.md")],
    )

    assert len(records) == 1
    assert records[0].rel_path == "HEARTBEAT.md"
    assert records[0].status == "changed"
    assert has_drift(records)


def test_compare_template_pairs_ignores_final_newline_only_drift(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    workspace = tmp_path / "workspace"
    templates.mkdir()
    workspace.mkdir()
    (templates / "BOARD_HEARTBEAT.md.j2").write_text(
        "heartbeat for {{ agent_name }}",
        encoding="utf-8",
    )
    (workspace / "HEARTBEAT.md").write_text(
        "heartbeat for Supervisor\n",
        encoding="utf-8",
    )

    records = compare_template_pairs(
        templates_root=templates,
        workspace_root=workspace,
        context={"agent_name": "Supervisor"},
        pairs=[("BOARD_HEARTBEAT.md.j2", "HEARTBEAT.md")],
    )

    assert records[0].status == "ok"
    assert not has_drift(records)
