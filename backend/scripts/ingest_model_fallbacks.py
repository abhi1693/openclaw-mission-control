#!/usr/bin/env python3
"""Ingest OpenClaw ``model_fallback_decision`` log events into MC pipeline events.

OpenClaw 2026.4.27 records first-class trajectory events when an agent's
fallback chain advances past a failed model candidate. The ``model_fallback``
state in MC's pipeline schema (``schemas/task_pipeline_events.py``) is
designed to carry these events, but the gateway log only stamps a UUID
``runId`` on them — not the ``mc-task-<id>-impl-<round>`` label that
identifies the parent task. This script reconstructs the missing
correlation by joining gateway log lines against MC task comments that
contain ``ACP_EXECUTOR_STARTED ... run=<uuid> label=mc-task-...``.

Designed to run as a periodic one-shot (cron) rather than a daemon.
Idempotency is enforced via a state file recording the hash of each posted
event so reruns are safe.

Usage::

    python ingest_model_fallbacks.py \\
        --gateway-log /tmp/openclaw/openclaw-2026-04-30.log \\
        --mc-base-url http://192.168.2.64:8000 \\
        --mc-token "$LOCAL_AUTH_TOKEN" \\
        --board-id 05002170-201b-4c66-bae1-26c0c833f206 \\
        --state-file /var/lib/mc-fallback-tailer/state.json
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

LOG = logging.getLogger("ingest_model_fallbacks")

# Generalized to accept any stage suffix after the task UUID — not just
# ``-impl-``. Review-only and validation-stage ACP children can also emit
# ``ACP_EXECUTOR_STARTED`` markers with labels like
# ``mc-task-<uuid>-review-<round>`` or ``-validation-<round>``; hardcoding
# ``-impl-`` would silently drop their fallback events. Codex F5 from the
# 2026-05-01 review.
EXECUTOR_STARTED_RE = re.compile(
    r"ACP_EXECUTOR_STARTED.*?run=(?P<run>[0-9a-f-]{36}).*?label=(?P<label>mc-task-[A-Za-z0-9_-]+)"
)
TASK_ID_FROM_LABEL_RE = re.compile(r"^mc-task-(?P<task_id>[0-9a-f-]{36})-")


@dataclasses.dataclass(frozen=True)
class FallbackEvent:
    """Normalized fallback-step event extracted from a gateway log line."""

    run_id: str
    timestamp: str
    from_model: str | None
    to_model: str | None
    reason: str | None
    chain_position: int | None
    final_outcome: str | None
    raw_subsystem: str

    def evidence(self) -> dict[str, Any]:
        """Build the ``evidence`` dict that MC's schema validator expects."""
        return {
            "from_model": self.from_model or "unknown",
            "to_model": self.to_model or "none",
            "reason": self.reason or "unknown",
            "chain_position": self.chain_position,
            "final_outcome": self.final_outcome,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "subsystem": self.raw_subsystem,
        }

    def idempotency_hash(self) -> str:
        """Stable identity for state-file dedup (run + timestamp + step)."""
        material = "|".join(
            [
                self.run_id,
                self.timestamp,
                self.from_model or "",
                self.to_model or "",
                str(self.chain_position),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def parse_gateway_log(log_path: Path) -> Iterator[FallbackEvent]:
    """Yield fallback events from a gateway log file.

    The log is JSONL-of-wrapped-JSON: each line is JSON with a ``"1"`` key
    holding the structured payload. We tolerate non-JSON lines (warnings,
    banner text) by skipping them.
    """
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                outer = json.loads(line)
            except json.JSONDecodeError:
                continue
            inner = outer.get("1")
            if not isinstance(inner, dict):
                continue
            if inner.get("event") != "model_fallback_decision":
                continue
            run_id = inner.get("runId")
            if not isinstance(run_id, str) or not run_id:
                continue
            yield FallbackEvent(
                run_id=run_id,
                timestamp=outer.get("time") or "",
                from_model=inner.get("fallbackStepFromModel"),
                to_model=inner.get("fallbackStepToModel"),
                reason=inner.get("fallbackStepFromFailureReason"),
                chain_position=inner.get("fallbackStepChainPosition"),
                final_outcome=inner.get("fallbackStepFinalOutcome"),
                raw_subsystem=(outer.get("_meta") or {}).get("name") or "",
            )


_PAGE_SIZE = 200
_MAX_PAGES = 50  # safety stop to avoid runaway pagination on a misbehaving API


def _paginate_get(
    *,
    base_url: str,
    path: str,
    token: str,
    timeout: int = 15,
) -> Iterator[dict[str, object]]:
    """Yield items from a paginated MC list endpoint.

    Walks ``offset`` until the page is empty OR ``offset + page_size >= total``
    (when the response carries a ``total`` field) OR the safety cap is hit.
    Tolerates list-shaped responses (no envelope) by yielding once and
    stopping. Codex F4 from the 2026-05-01 review.
    """
    for page_idx in range(_MAX_PAGES):
        offset = page_idx * _PAGE_SIZE
        url = f"{base_url}{path}?limit={_PAGE_SIZE}&offset={offset}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
        if isinstance(body, list):
            yield from body
            return
        items = body.get("items", []) if isinstance(body, dict) else []
        if not items:
            return
        yield from items
        total = body.get("total") if isinstance(body, dict) else None
        if isinstance(total, int) and offset + _PAGE_SIZE >= total:
            return


def fetch_executor_started_comments(
    *,
    mc_base_url: str,
    mc_token: str,
    board_id: str,
) -> dict[str, str]:
    """Build a ``run_uuid → task_id`` map from ACP_EXECUTOR_STARTED markers.

    Walks recent comments on every task in the board and parses the markers.
    For boards with many tasks this is N HTTP calls; acceptable for the
    cron cadence. Both the task list and the per-task comments are
    paginated (Codex F4) so boards with > 200 tasks or tasks with > 200
    comments do not silently drop markers from later pages.
    """
    run_to_task: dict[str, str] = {}
    for task in _paginate_get(
        base_url=mc_base_url,
        path=f"/api/v1/boards/{board_id}/tasks",
        token=mc_token,
    ):
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            comments = list(
                _paginate_get(
                    base_url=mc_base_url,
                    path=f"/api/v1/boards/{board_id}/tasks/{task_id}/comments",
                    token=mc_token,
                )
            )
        except urllib.error.HTTPError as exc:
            LOG.warning("comments fetch failed task=%s status=%s", task_id, exc.code)
            continue
        for comment in comments:
            message = comment.get("message") or ""
            if not isinstance(message, str):
                continue
            for match in EXECUTOR_STARTED_RE.finditer(message):
                run = match.group("run")
                label_match = TASK_ID_FROM_LABEL_RE.match(match.group("label"))
                if not label_match:
                    continue
                # Prefer the label-derived task_id over the comment's task_id
                # in case a parent posts a marker about a child task.
                run_to_task[run] = label_match.group("task_id")
    return run_to_task


def post_pipeline_event(
    *,
    mc_base_url: str,
    mc_token: str,
    board_id: str,
    task_id: str,
    event: FallbackEvent,
) -> None:
    url = f"{mc_base_url}/api/v1/boards/{board_id}/tasks/{task_id}/pipeline/events"
    payload = {
        "state": "model_fallback",
        "source": "ingest_model_fallbacks.py",
        "evidence": event.evidence(),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {mc_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def load_state(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()
    try:
        return set(json.loads(state_file.read_text()).get("posted_hashes", []))
    except (json.JSONDecodeError, OSError):
        LOG.warning("state file %s unreadable, starting fresh", state_file)
        return set()


def save_state(state_file: Path, posted_hashes: set[str]) -> None:
    """Write the state file atomically (write tmp + os.replace).

    Plain ``write_text`` is not atomic — a crash mid-write or a concurrent
    cron overlap can leave a truncated state file. The tmp + replace
    pattern guarantees readers see either the old or the new state, never
    a partial one. Codex F6 from the 2026-05-01 review.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"posted_hashes": sorted(posted_hashes)}, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        prefix=state_file.name + ".",
        suffix=".tmp",
        dir=state_file.parent,
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, state_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def ingest(
    *,
    gateway_logs: Iterable[Path],
    mc_base_url: str,
    mc_token: str,
    board_id: str,
    state_file: Path,
    dry_run: bool,
) -> dict[str, int]:
    posted = load_state(state_file)
    run_to_task = fetch_executor_started_comments(
        mc_base_url=mc_base_url, mc_token=mc_token, board_id=board_id
    )
    LOG.info("indexed %d run-id → task-id mappings", len(run_to_task))

    counters = {"seen": 0, "matched": 0, "skipped_dup": 0, "posted": 0, "failed": 0}
    for log_path in gateway_logs:
        for event in parse_gateway_log(log_path):
            counters["seen"] += 1
            task_id = run_to_task.get(event.run_id)
            if task_id is None:
                continue
            counters["matched"] += 1
            event_hash = event.idempotency_hash()
            if event_hash in posted:
                counters["skipped_dup"] += 1
                continue
            if dry_run:
                LOG.info(
                    "[dry-run] would post task=%s hash=%s from=%s to=%s",
                    task_id,
                    event_hash,
                    event.from_model,
                    event.to_model,
                )
                continue
            try:
                post_pipeline_event(
                    mc_base_url=mc_base_url,
                    mc_token=mc_token,
                    board_id=board_id,
                    task_id=task_id,
                    event=event,
                )
            except urllib.error.HTTPError as exc:
                LOG.warning(
                    "post failed task=%s hash=%s status=%s body=%s",
                    task_id,
                    event_hash,
                    exc.code,
                    exc.read()[:200],
                )
                counters["failed"] += 1
                continue
            posted.add(event_hash)
            counters["posted"] += 1
    if not dry_run:
        save_state(state_file, posted)
    return counters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gateway-log",
        action="append",
        required=True,
        type=Path,
        help="Path to a gateway log file. May be passed multiple times.",
    )
    parser.add_argument("--mc-base-url", required=True)
    parser.add_argument("--mc-token", required=True)
    parser.add_argument("--board-id", required=True)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/var/lib/mc-fallback-tailer/state.json"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and match but do not POST or update state file.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    counters = ingest(
        gateway_logs=args.gateway_log,
        mc_base_url=args.mc_base_url.rstrip("/"),
        mc_token=args.mc_token,
        board_id=args.board_id,
        state_file=args.state_file,
        dry_run=args.dry_run,
    )
    LOG.info("done: %s", counters)
    return 0


if __name__ == "__main__":
    sys.exit(main())
