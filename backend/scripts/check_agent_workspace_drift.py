"""Read-only checksum drift checker for active agent workspaces.

The script compares canonical skill files and optionally rendered template
pairs against an existing OpenClaw agent workspace. It never writes files or
calls Mission Control APIs; non-zero exit means drift was found.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


@dataclass(frozen=True)
class DriftRecord:
    """One file comparison result."""

    rel_path: str
    status: str
    expected_sha256: str | None
    actual_sha256: str | None
    expected_bytes: int | None
    actual_bytes: int | None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file():
        return None
    return path.read_bytes()


def _record(rel_path: str, expected: bytes, actual: bytes | None) -> DriftRecord:
    expected_sha = _sha256_bytes(expected)
    if actual is None:
        return DriftRecord(
            rel_path=rel_path,
            status="missing",
            expected_sha256=expected_sha,
            actual_sha256=None,
            expected_bytes=len(expected),
            actual_bytes=None,
        )
    actual_sha = _sha256_bytes(actual)
    return DriftRecord(
        rel_path=rel_path,
        status="ok" if expected_sha == actual_sha else "changed",
        expected_sha256=expected_sha,
        actual_sha256=actual_sha,
        expected_bytes=len(expected),
        actual_bytes=len(actual),
    )


def _strip_text_bytes(data: bytes | None) -> bytes | None:
    if data is None:
        return None
    return data.decode("utf-8").strip().encode()


def compare_skill_roots(
    canonical_skills_root: Path,
    workspace_skills_root: Path,
    *,
    skill_names: set[str] | None = None,
) -> list[DriftRecord]:
    """Compare ``*/SKILL.md`` files from a canonical skill root."""

    records: list[DriftRecord] = []
    found_skill_names: set[str] = set()
    for expected_path in sorted(canonical_skills_root.glob("*/SKILL.md")):
        skill_name = expected_path.parent.name
        if skill_names is not None and skill_name not in skill_names:
            continue
        found_skill_names.add(skill_name)
        rel_path = f"skills/{skill_name}/SKILL.md"
        actual_path = workspace_skills_root / skill_name / "SKILL.md"
        expected = expected_path.read_bytes()
        actual = _read_bytes(actual_path)
        records.append(_record(rel_path, expected, actual))
    if skill_names is not None:
        for skill_name in sorted(skill_names - found_skill_names):
            records.append(
                DriftRecord(
                    rel_path=f"skills/{skill_name}/SKILL.md",
                    status="missing_canonical",
                    expected_sha256=None,
                    actual_sha256=None,
                    expected_bytes=None,
                    actual_bytes=None,
                )
            )
    return records


def _template_env(templates_root: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_root)),
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def compare_template_pairs(
    *,
    templates_root: Path,
    workspace_root: Path,
    context: dict[str, Any],
    pairs: list[tuple[str, str]],
) -> list[DriftRecord]:
    """Render templates and compare them with files in an active workspace."""

    env = _template_env(templates_root)
    records: list[DriftRecord] = []
    for template_name, workspace_rel_path in pairs:
        rendered = env.get_template(template_name).render(**context).strip().encode()
        actual = _strip_text_bytes(_read_bytes(workspace_root / workspace_rel_path))
        records.append(_record(workspace_rel_path, rendered, actual))
    return records


def has_drift(records: list[DriftRecord]) -> bool:
    return any(record.status != "ok" for record in records)


def _parse_pair(value: str) -> tuple[str, str]:
    if ":" not in value:
        msg = "template pairs must use TEMPLATE:WORKSPACE_REL_PATH"
        raise argparse.ArgumentTypeError(msg)
    template_name, rel_path = value.split(":", 1)
    if not template_name or not rel_path:
        msg = "template pair cannot contain an empty side"
        raise argparse.ArgumentTypeError(msg)
    return template_name, rel_path


def _build_parser() -> argparse.ArgumentParser:
    default_backend = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Check active agent workspace files for read-only drift.",
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--canonical-skills-root",
        type=Path,
        default=default_backend / "skills",
    )
    parser.add_argument(
        "--templates-root",
        type=Path,
        default=default_backend / "templates",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Limit skill checks to a specific skill name; repeatable.",
    )
    parser.add_argument(
        "--template-context-json",
        type=Path,
        help="JSON file used to render template pairs.",
    )
    parser.add_argument(
        "--template-pair",
        action="append",
        type=_parse_pair,
        default=[],
        help="Template/workspace pair as TEMPLATE.md.j2:RENDERED.md; repeatable.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--include-ok",
        action="store_true",
        help="Include matching files in text output.",
    )
    return parser


def _load_context(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "template context JSON must be an object"
        raise SystemExit(msg)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    skill_names = set(args.skill) if args.skill else None

    records = compare_skill_roots(
        args.canonical_skills_root,
        args.workspace_root / "skills",
        skill_names=skill_names,
    )
    if args.template_pair:
        records.extend(
            compare_template_pairs(
                templates_root=args.templates_root,
                workspace_root=args.workspace_root,
                context=_load_context(args.template_context_json),
                pairs=args.template_pair,
            )
        )

    if args.json:
        print(json.dumps([asdict(record) for record in records], indent=2))
    else:
        shown = records if args.include_ok else [r for r in records if r.status != "ok"]
        for record in shown:
            print(
                f"{record.status}\t{record.rel_path}\t"
                f"expected={record.expected_sha256 or '-'}\t"
                f"actual={record.actual_sha256 or '-'}"
            )
        if not shown:
            print("no drift")
    return 1 if has_drift(records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
