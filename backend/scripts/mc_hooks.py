#!/usr/bin/env python3
"""Typed CLI for OpenClaw inbound hooks (``POST /hooks/wake`` and
``POST /hooks/agent``). Wraps the gateway's hook-token auth, base-URL
resolution, and JSON encoding so MC operator cron / scripts don't
hand-roll curl strings.

Companion to ``mc_client.py``. Talks to the OpenClaw gateway (default
``http://127.0.0.1:18789``), not the MC backend.

Usage::

    mc_hooks.py wake --text "external trigger fired"
    mc_hooks.py agent --message "summarize today's PRs" --model openai-codex/gpt-5.4
    cat body.md | mc_hooks.py agent --message - --name nightly-pr-summary

Token resolution order:
  1. ``--token``
  2. env var ``OPENCLAW_HOOK_TOKEN``
  3. ``OPENCLAW_HOOK_TOKEN=<value>`` line inside ``/etc/mc-hooks/env``

Base URL resolution order:
  1. ``--base-url``
  2. env var ``OPENCLAW_HOOK_URL``
  3. ``http://127.0.0.1:18789`` (gateway control server)

Exit codes:
  0  success
  1  argument / config error
  2  HTTP non-2xx response
  3  network / decode error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:18789"
DEFAULT_TOKEN_FILE = "/etc/mc-hooks/env"


class HttpError(RuntimeError):
    """Non-2xx HTTP response. Caught by ``main()`` and translated to exit code 2."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def _resolve_token(args: argparse.Namespace) -> str:
    flag = getattr(args, "token", None)
    if flag:
        return str(flag)
    env = os.environ.get("OPENCLAW_HOOK_TOKEN")
    if env:
        return env
    token = _read_token_file(DEFAULT_TOKEN_FILE)
    if token:
        return token
    raise SystemExit(
        "OPENCLAW_HOOK_TOKEN not provided. Pass --token, set "
        f"OPENCLAW_HOOK_TOKEN, or write OPENCLAW_HOOK_TOKEN=<value> to "
        f"{DEFAULT_TOKEN_FILE} (mode 0600)."
    )


def _read_token_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                if key.strip() == "OPENCLAW_HOOK_TOKEN":
                    return value.strip().strip("\"'")
    except OSError:
        return None
    return None


def _resolve_base_url(args: argparse.Namespace) -> str:
    flag = getattr(args, "base_url", None)
    base = flag or os.environ.get("OPENCLAW_HOOK_URL") or DEFAULT_BASE_URL
    return base.rstrip("/")


def _resolve_message_stdin(args: argparse.Namespace) -> None:
    """When --message is '-', replace it with stdin contents in place.

    Trailing newlines are stripped (interactive paste behavior); other
    whitespace is preserved verbatim. Empty stdin exits non-zero —
    avoids posting empty-body agent runs.
    """
    if getattr(args, "message", None) != "-":
        return
    body = sys.stdin.read()
    body = body.rstrip("\n").rstrip()
    if not body:
        raise SystemExit("--message - reading from stdin produced empty body")
    args.message = body


def _request(*, method: str, url: str, token: str, payload: dict[str, Any]) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise HttpError(exc.code, body) from exc
    if not raw:
        return {}
    return json.loads(raw)


# --- subcommand handlers ---


def cmd_wake(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args)
    base = _resolve_base_url(args)
    payload = {"text": args.text, "mode": args.mode}
    return _request(  # type: ignore[return-value]
        method="POST",
        url=f"{base}/hooks/wake",
        token=token,
        payload=payload,
    )


def cmd_agent(args: argparse.Namespace) -> dict[str, Any]:
    _resolve_message_stdin(args)
    token = _resolve_token(args)
    base = _resolve_base_url(args)
    payload: dict[str, Any] = {"message": args.message}
    if args.name:
        payload["name"] = args.name
    if args.agent_id:
        payload["agentId"] = args.agent_id
    if args.model:
        payload["model"] = args.model
    if args.thinking:
        payload["thinking"] = args.thinking
    if args.channel:
        payload["channel"] = args.channel
    if args.to:
        payload["to"] = args.to
    if args.deliver:
        payload["deliver"] = True
    if args.timeout_seconds is not None:
        payload["timeoutSeconds"] = int(args.timeout_seconds)
    return _request(  # type: ignore[return-value]
        method="POST",
        url=f"{base}/hooks/agent",
        token=token,
        payload=payload,
    )


# --- argparse wiring ---


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Typed client for OpenClaw inbound hooks "
            "(POST /hooks/wake, POST /hooks/agent). Wraps auth, base "
            "URL resolution, and JSON encoding."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Gateway base URL (env: OPENCLAW_HOOK_URL, default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help=(
            "Hook token (env: OPENCLAW_HOOK_TOKEN, fallback file: "
            f"{DEFAULT_TOKEN_FILE}). NOT the operator MC token."
        ),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (default: compact).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub_wake = sub.add_parser(
        "wake",
        help="Queue a system event for the main session.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_wake.add_argument("--text", required=True, help="Event description.")
    sub_wake.add_argument(
        "--mode",
        default="next-heartbeat",
        choices=["now", "next-heartbeat"],
        help="Delivery timing.",
    )
    sub_wake.set_defaults(func=cmd_wake)

    sub_agent = sub.add_parser(
        "agent",
        help="Run an isolated agent turn.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub_agent.add_argument(
        "--message",
        required=True,
        help="Prompt body. Use '-' for stdin.",
    )
    sub_agent.add_argument("--name", default=None, help="Job/run label.")
    sub_agent.add_argument(
        "--agent-id",
        default=None,
        help="Constrained by hooks.allowedAgentIds in gateway config.",
    )
    sub_agent.add_argument("--model", default=None, help="Model override (provider/model).")
    sub_agent.add_argument(
        "--thinking",
        default=None,
        choices=["off", "low", "medium", "high"],
        help="Thinking level override.",
    )
    sub_agent.add_argument(
        "--channel",
        default=None,
        help="Delivery channel (e.g., slack, telegram).",
    )
    sub_agent.add_argument(
        "--to",
        default=None,
        help="Delivery target ID (e.g., channel:C1234567890).",
    )
    sub_agent.add_argument(
        "--deliver",
        action="store_true",
        help="Deliver the agent's reply to the channel/target (default: false).",
    )
    sub_agent.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Run timeout in seconds.",
    )
    sub_agent.set_defaults(func=cmd_agent)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except HttpError as exc:
        sys.stderr.write(f"HTTP {exc.status}: {exc.body[:500]}\n")
        return 2
    except urllib.error.URLError as exc:
        sys.stderr.write(f"network error: {exc.reason}\n")
        return 3
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"non-JSON response: {exc}\n")
        return 3
    if args.pretty:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
