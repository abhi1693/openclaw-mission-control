#!/usr/bin/env python3
"""Lightweight markdown link checker for repo docs.

Checks *relative* links inside markdown files and fails CI if any targets are missing.

Design goals:
- No external deps.
- Ignore http(s)/mailto links.
- Ignore pure anchors (#foo).
- Support links with anchors (./path.md#section) by checking only the path part.

Limitations:
- Does not validate that anchors exist inside target files.
- Does not validate links generated dynamically or via HTML.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def iter_md_files(root: Path) -> list[Path]:
    """Return markdown files to check.

    Policy:
    - Always check root contributor-facing markdown (`README.md`, `CONTRIBUTING.md`).
    - If `docs/` exists, also check `docs/**/*.md`.

    Rationale:
    - We want fast feedback on broken *relative* links in the most important entrypoints.
    - We intentionally do **not** crawl external URLs.
    """

    files: list[Path] = []

    for p in (root / "README.md", root / "CONTRIBUTING.md"):
        if p.exists():
            files.append(p)

    docs = root / "docs"
    if docs.exists():
        files.extend(sorted(docs.rglob("*.md")))

    # de-dupe + stable order
    return sorted({p.resolve() for p in files})


def normalize_target(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("mailto:"):
        return None
    if raw.startswith("#"):
        return None
    # strip query/fragment
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    if not raw:
        return None
    return raw


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    md_files = iter_md_files(root)

    missing: list[tuple[Path, str]] = []

    for md in md_files:
        text = md.read_text(encoding="utf-8")
        for m in LINK_RE.finditer(text):
            target_raw = m.group(1)
            target = normalize_target(target_raw)
            if target is None:
                continue

            # Skip common markdown reference-style quirks.
            if target.startswith("<") and target.endswith(">"):
                continue

            # Resolve relative to current file.
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                missing.append((md, target_raw))

    if missing:
        print("Broken relative links detected:\n")
        for md, target in missing:
            print(f"- {md.relative_to(root)} -> {target}")
        print(f"\nTotal: {len(missing)}")
        return 1

    print(f"OK: checked {len(md_files)} markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
