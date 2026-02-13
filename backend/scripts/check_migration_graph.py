"""Migration graph integrity checks for CI.

Checks:
- alembic script graph can be loaded (detects broken/missing links)
- single head by default (unless ALLOW_MULTIPLE_HEADS=true)
- no orphan revisions (all revisions reachable from heads)
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    alembic_ini = root / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.attributes["configure_logger"] = False

    try:
        script = ScriptDirectory.from_config(cfg)
    except Exception as exc:  # pragma: no cover - CI path
        print(f"ERROR: unable to load Alembic script directory: {exc}")
        return 1

    try:
        heads = list(script.get_heads())
    except Exception as exc:  # pragma: no cover - CI path
        print(f"ERROR: unable to resolve Alembic heads: {exc}")
        return 1

    allow_multiple_heads = _truthy(os.getenv("ALLOW_MULTIPLE_HEADS"))
    if not heads:
        print("ERROR: no Alembic heads found")
        return 1

    if len(heads) > 1 and not allow_multiple_heads:
        print(
            "ERROR: multiple Alembic heads detected (set ALLOW_MULTIPLE_HEADS=true only for intentional merge windows)"
        )
        for h in heads:
            print(f"  - {h}")
        return 1

    try:
        reachable: set[str] = set()
        for walk_rev in script.walk_revisions(base="base", head="heads"):
            if walk_rev is None:
                continue
            if walk_rev.revision:
                reachable.add(walk_rev.revision)
    except Exception as exc:  # pragma: no cover - CI path
        print(f"ERROR: failed while walking Alembic revision graph: {exc}")
        return 1

    all_revisions: set[str] = set()
    # Alembic's revision_map is dynamically typed; guard None values.
    for map_rev in script.revision_map._revision_map.values():
        if map_rev is None:
            continue
        revision = getattr(map_rev, "revision", None)
        if revision:
            all_revisions.add(revision)

    orphans = sorted(all_revisions - reachable)
    if orphans:
        print("ERROR: orphan Alembic revisions detected (not reachable from heads):")
        for orphan_rev in orphans:
            print(f"  - {orphan_rev}")
        return 1

    print("OK: migration graph integrity passed")
    print(f"Heads: {', '.join(heads)}")
    print(f"Reachable revisions: {len(reachable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
