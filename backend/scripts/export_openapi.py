"""Export the backend OpenAPI schema to a versioned JSON artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    """Generate `openapi.json` from the FastAPI app definition."""
    from app.main import app

    # Importing the FastAPI app does not run lifespan hooks,
    # so this does not require a DB.
    out_path = BACKEND_ROOT / "openapi.json"
    payload = app.openapi()
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.stdout.write(f"{out_path}\n")


if __name__ == "__main__":
    main()
