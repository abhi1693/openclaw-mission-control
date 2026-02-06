from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    # Importing the FastAPI app does not run lifespan hooks, so this does not require a DB.
    out_path = BACKEND_ROOT / "openapi.json"
    payload = app.openapi()
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
