"""Local OpenClaw runtime status helpers."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass


DEFAULT_OPENCLAW_STATUS_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeStatusSnapshot:
    """Result from the local ``openclaw status --json`` command."""

    ok: bool
    payload: object | None = None
    error: str | None = None
    return_code: int | None = None


def extract_json_payload(text: str) -> object:
    """Extract the first JSON value from CLI output.

    OpenClaw can print config warnings before ``--json`` output. The JSON
    payload is still valid once those human-readable warning lines are skipped.
    """

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
            return payload
        except json.JSONDecodeError:
            continue
    raise ValueError("OpenClaw status output did not contain JSON")


def _run_openclaw_status(timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["openclaw", "status", "--json"],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


async def collect_openclaw_status(
    *,
    timeout_seconds: int = DEFAULT_OPENCLAW_STATUS_TIMEOUT_SECONDS,
) -> OpenClawRuntimeStatusSnapshot:
    """Collect a best-effort local OpenClaw runtime status snapshot."""

    try:
        completed = await asyncio.to_thread(_run_openclaw_status, timeout_seconds)
    except FileNotFoundError:
        return OpenClawRuntimeStatusSnapshot(
            ok=False,
            error="openclaw executable not found",
        )
    except subprocess.TimeoutExpired:
        return OpenClawRuntimeStatusSnapshot(
            ok=False,
            error=f"openclaw status timed out after {timeout_seconds}s",
        )
    except OSError as exc:
        return OpenClawRuntimeStatusSnapshot(
            ok=False,
            error=f"openclaw status failed: {exc}",
        )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return OpenClawRuntimeStatusSnapshot(
            ok=False,
            error=detail or f"openclaw status exited with code {completed.returncode}",
            return_code=completed.returncode,
        )

    try:
        payload = extract_json_payload(completed.stdout)
    except ValueError as exc:
        return OpenClawRuntimeStatusSnapshot(
            ok=False,
            error=str(exc),
            return_code=completed.returncode,
        )

    return OpenClawRuntimeStatusSnapshot(
        ok=True,
        payload=payload,
        return_code=completed.returncode,
    )
