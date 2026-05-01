#!/usr/bin/env python3
"""Mission Control board API client for ACP children and other automations.

Replaces the curl-with-auth-token construction pattern that ACP children
currently hand-roll in skills. The same operations (task read, comment
create, pipeline event create, review event create) become typed CLI
calls. Auth is read from the ``LOCAL_AUTH_TOKEN`` env var the spawn parent
already provides.

Environment::

    MC_BASE_URL       defaults to http://192.168.2.64:8000
    LOCAL_AUTH_TOKEN  required for all calls (override with --token)
    BOARD_ID          required for task-scoped subcommands (override with --board)

Usage::

    mc_client.py task-read --task <task-id>
    mc_client.py comment-create --task <task-id> --message "Body..."
    mc_client.py pipeline-event-create --task <task-id> --state committed --commit-sha abc1234
    mc_client.py review-event-create --task <task-id> --reviewer-role architect --verdict pass \\
        --evidence '{"comment": "..."}' --commit-sha abc1234 --build-hash index-x.js \\
        --target http://192.168.2.63:3002/

Exit codes::

    0  success
    1  argument / config error
    2  HTTP non-2xx response (body printed to stderr)
    3  network / decoding error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://192.168.2.64:8000"


# --- HTTP plumbing ---


class HttpError(RuntimeError):
    """A non-2xx response from MC. ``body`` is the raw response payload."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def _request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> dict[str, Any] | list[Any]:
    headers = {"Authorization": f"Bearer {token}"}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, body) from exc
    if not raw:
        return {}
    return json.loads(raw)


def _resolve_token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("LOCAL_AUTH_TOKEN")
    if not token:
        raise SystemExit(
            "no auth token: set LOCAL_AUTH_TOKEN env var or pass --token"
        )
    return token


def _resolve_board(args: argparse.Namespace) -> str:
    """Resolve the board id, with cross-board guard.

    The skill at ``backend/skills/mc-board-api/SKILL.md`` documents that
    the CLI prevents accidental cross-board writes. Enforce that here:
    if both ``--board`` and ``$BOARD_ID`` are set and they disagree, abort
    rather than silently use the override. Codex re-pass finding from the
    2026-05-01 third review.
    """
    env_board = os.environ.get("BOARD_ID") or None
    flag_board = args.board or None
    if flag_board and env_board and flag_board != env_board:
        raise SystemExit(
            f"--board {flag_board!r} does not match $BOARD_ID {env_board!r}; "
            "refusing to write to a different board than the one the spawn "
            "parent provisioned. Unset BOARD_ID or pass the matching value."
        )
    board = flag_board or env_board
    if not board:
        raise SystemExit(
            "no board id: set BOARD_ID env var or pass --board"
        )
    return board


def _resolve_base_url(args: argparse.Namespace) -> str:
    base = args.base_url or os.environ.get("MC_BASE_URL") or DEFAULT_BASE_URL
    return base.rstrip("/")


def _parse_evidence(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--evidence is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--evidence must be a JSON object, not a list/scalar")
    return parsed


# --- subcommand handlers ---


def cmd_task_read(args: argparse.Namespace) -> dict[str, Any]:
    """Read one task by id via the single-task GET endpoint.

    Returns the task envelope or raises HttpError(404) if the task
    does not belong to the configured board.
    """
    token = _resolve_token(args)
    board = _resolve_board(args)
    base = _resolve_base_url(args)
    url = f"{base}/api/v1/boards/{board}/tasks/{args.task}"
    return _request(method="GET", url=url, token=token)  # type: ignore[return-value]


def cmd_comment_create(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args)
    board = _resolve_board(args)
    base = _resolve_base_url(args)
    if not args.message or not args.message.strip():
        raise SystemExit("--message is required and must be non-empty")
    url = f"{base}/api/v1/boards/{board}/tasks/{args.task}/comments"
    return _request(  # type: ignore[return-value]
        method="POST",
        url=url,
        token=token,
        payload={"message": args.message},
    )


def cmd_pipeline_event_create(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args)
    board = _resolve_board(args)
    base = _resolve_base_url(args)
    payload: dict[str, Any] = {"state": args.state}
    if args.source:
        payload["source"] = args.source
    if args.commit_sha:
        payload["commit_sha"] = args.commit_sha
    if args.artifact_hash:
        payload["artifact_hash"] = args.artifact_hash
    if args.deploy_target:
        payload["deploy_target"] = args.deploy_target
    if args.live_sha:
        payload["live_sha"] = args.live_sha
    evidence = _parse_evidence(args.evidence)
    if evidence is not None:
        payload["evidence"] = evidence
    url = f"{base}/api/v1/boards/{board}/tasks/{args.task}/pipeline/events"
    return _request(  # type: ignore[return-value]
        method="POST",
        url=url,
        token=token,
        payload=payload,
    )


def cmd_review_event_create(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args)
    board = _resolve_board(args)
    base = _resolve_base_url(args)
    payload: dict[str, Any] = {
        "reviewer_role": args.reviewer_role,
        "verdict": args.verdict,
    }
    if args.evidence_type:
        payload["evidence_type"] = args.evidence_type
    if args.target:
        payload["target"] = args.target
    if args.build_hash:
        payload["build_hash"] = args.build_hash
    if args.commit_sha:
        payload["source_commit"] = args.commit_sha
    if args.blocking_owner:
        payload["blocking_owner"] = args.blocking_owner
    if args.suggested_routing:
        payload["suggested_routing"] = args.suggested_routing
    evidence = _parse_evidence(args.evidence)
    if evidence is not None:
        payload["evidence"] = evidence
    url = f"{base}/api/v1/boards/{board}/tasks/{args.task}/review-events"
    return _request(  # type: ignore[return-value]
        method="POST",
        url=url,
        token=token,
        payload=payload,
    )


# --- argparse wiring ---


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mission Control board API client (replaces hand-rolled curl in ACP child skills).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"MC base URL (env: MC_BASE_URL, default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="MC auth token (env: LOCAL_AUTH_TOKEN). Required.",
    )
    parser.add_argument(
        "--board",
        default=None,
        help="Board UUID (env: BOARD_ID). Required for task-scoped commands.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (default: compact).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # task-read
    sub_task_read = subparsers.add_parser(
        "task-read",
        help="Fetch a task by id.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_task_read.add_argument("--task", required=True, help="Task UUID.")
    sub_task_read.set_defaults(func=cmd_task_read)

    # comment-create
    sub_comment = subparsers.add_parser(
        "comment-create",
        help="Post a task comment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_comment.add_argument("--task", required=True, help="Task UUID.")
    sub_comment.add_argument(
        "--message",
        required=True,
        help="Comment body (Markdown). Use - for stdin.",
    )
    sub_comment.set_defaults(func=cmd_comment_create)

    # pipeline-event-create
    sub_pipeline = subparsers.add_parser(
        "pipeline-event-create",
        help="Append a structured pipeline event to a task cycle.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_pipeline.add_argument("--task", required=True, help="Task UUID.")
    sub_pipeline.add_argument(
        "--state",
        required=True,
        choices=[
            "code_changed",
            "committed",
            "built",
            "deployed",
            "live_build_verified",
            "runtime_verified",
            "qa_ready",
            "model_fallback",
        ],
        help="Pipeline state for this event.",
    )
    sub_pipeline.add_argument("--source", default="mc_client.py")
    sub_pipeline.add_argument("--commit-sha", default=None)
    sub_pipeline.add_argument("--artifact-hash", default=None)
    sub_pipeline.add_argument("--deploy-target", default=None)
    sub_pipeline.add_argument("--live-sha", default=None)
    sub_pipeline.add_argument(
        "--evidence",
        default=None,
        help="JSON object string. Required for state=model_fallback per schema validator.",
    )
    sub_pipeline.set_defaults(func=cmd_pipeline_event_create)

    # review-event-create
    sub_review = subparsers.add_parser(
        "review-event-create",
        help="Post a structured review event (reviewer verdict).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_review.add_argument("--task", required=True, help="Task UUID.")
    sub_review.add_argument(
        "--reviewer-role",
        required=True,
        choices=["architect", "qa_unit", "qa_e2e", "devops", "lead"],
    )
    sub_review.add_argument(
        "--verdict",
        required=True,
        # Mirrors backend/app/schemas/task_review_events.py ReviewVerdict
        # Literal — keep in sync if MC's schema changes.
        choices=["pass", "fail", "inconclusive", "infra_blocked"],
    )
    sub_review.add_argument("--evidence-type", default=None)
    sub_review.add_argument("--target", default=None)
    sub_review.add_argument("--build-hash", default=None)
    sub_review.add_argument("--commit-sha", default=None)
    sub_review.add_argument(
        "--blocking-owner",
        default=None,
        help="For FAIL/INCONCLUSIVE: who must fix it (e.g. PF, PB, DevOps).",
    )
    sub_review.add_argument(
        "--suggested-routing",
        default=None,
        help="Free-form routing hint for the lead (e.g. 'lead move to rework for PF').",
    )
    sub_review.add_argument(
        "--evidence",
        default=None,
        help="JSON object string with reviewer-specific evidence.",
    )
    sub_review.set_defaults(func=cmd_review_event_create)

    return parser


def _resolve_message_stdin(args: argparse.Namespace) -> None:
    """If --message is '-', read from stdin. Mutates args in place."""
    if getattr(args, "message", None) == "-":
        args.message = sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_message_stdin(args)

    try:
        result = args.func(args)
    except HttpError as exc:
        sys.stderr.write(f"HTTP {exc.status}: {exc.body}\n")
        return 2
    except urllib.error.URLError as exc:
        sys.stderr.write(f"network error: {exc.reason}\n")
        return 3
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"response is not JSON: {exc}\n")
        return 3

    if args.pretty:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
