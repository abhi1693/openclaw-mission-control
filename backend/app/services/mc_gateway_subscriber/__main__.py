"""Worker entry point: ``python -m app.services.mc_gateway_subscriber``.

Resolves config from env (env var > env file > error), constructs a
``Subscriber``, and runs until SIGTERM/SIGINT. Designed to be run by
systemd (or any process supervisor); see
``docs/plans/2026-05-02-gateway-event-subscriber-design.md`` for the
deploy model.

Configuration:
  OPENCLAW_GATEWAY_WS_URL  ws:// or wss:// URL of the gateway
                           (e.g. ws://192.168.2.60:18789/ws)
  OPENCLAW_GATEWAY_TOKEN   bearer token from a paired operator device

Resolution order: explicit env var > value in ``DEFAULT_ENV_FILE``
(``/etc/mc-gateway-subscriber/env``, mode 0600).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.mc_gateway_subscriber.subscriber import Subscriber

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE = "/etc/mc-gateway-subscriber/env"
DEFAULT_SUBSCRIPTIONS = ("sessions.subscribe",)


@dataclass(frozen=True)
class SubscriberConfig:
    url: str
    token: str
    subscriptions: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS


def load_env_file(path: str) -> dict[str, str]:
    """Parse a shell-env-style file. Returns ``{}`` if the file is missing.

    Unquoted values: everything up to first ``#`` (inline comment),
    then trimmed. Quoted values (``"..."`` or ``'...'``): preserved
    verbatim. CRLF normalized.
    """
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n").strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key:
                    continue
                out[key] = _parse_env_value(value)
    except OSError:
        return {}
    return out


def _parse_env_value(raw: str) -> str:
    value = raw.lstrip()
    if value.startswith('"'):
        end = value.find('"', 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    if value.startswith("'"):
        end = value.find("'", 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    hash_idx = value.find("#")
    if hash_idx != -1:
        value = value[:hash_idx]
    return value.strip()


def resolve_config(
    *,
    env_file_path: str = DEFAULT_ENV_FILE,
    subscriptions: Sequence[str] = DEFAULT_SUBSCRIPTIONS,
) -> SubscriberConfig:
    """Resolve URL + token from env-var-then-file. Exits on missing required."""
    file_cfg = load_env_file(env_file_path)
    url = os.environ.get("OPENCLAW_GATEWAY_WS_URL") or file_cfg.get("OPENCLAW_GATEWAY_WS_URL")
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or file_cfg.get("OPENCLAW_GATEWAY_TOKEN")
    if not url:
        raise SystemExit(
            "OPENCLAW_GATEWAY_WS_URL not set. Provide env var or write "
            f"OPENCLAW_GATEWAY_WS_URL=<value> to {env_file_path}."
        )
    if not token:
        raise SystemExit(
            "OPENCLAW_GATEWAY_TOKEN not set. Provide env var or write "
            f"OPENCLAW_GATEWAY_TOKEN=<value> to {env_file_path}."
        )
    return SubscriberConfig(url=url, token=token, subscriptions=tuple(subscriptions))


async def run_async(stop: asyncio.Event, config: SubscriberConfig) -> None:
    """Construct a Subscriber and run until ``stop`` is set."""
    sub = Subscriber(
        url=config.url,
        token=config.token,
        subscriptions=config.subscriptions,
    )
    # Future slices register handlers here, e.g.:
    #   sub.on("sessions.changed", projector_for_sessions_changed)
    await sub.run(stop)


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = resolve_config()
    stop = asyncio.Event()

    def _request_stop(*_: object) -> None:
        logger.info("received shutdown signal; closing")
        stop.set()

    loop = asyncio.new_event_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _request_stop)
        loop.run_until_complete(run_async(stop, config))
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
