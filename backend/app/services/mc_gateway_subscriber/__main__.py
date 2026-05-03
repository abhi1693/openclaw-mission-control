"""Worker entry point: ``python -m app.services.mc_gateway_subscriber``.

Resolves config from env (env var > env file > error), constructs a
``Subscriber`` and a worker-private DB engine, and runs until SIGTERM
or SIGINT. Designed to be run by systemd (or any process supervisor);
see ``docs/plans/2026-05-02-gateway-event-subscriber-design.md`` for
the deploy model.

Required env (env var > env file):
  OPENCLAW_GATEWAY_WS_URL  ws:// or wss:// URL of the gateway
                           (e.g. ws://192.168.2.60:18789/ws)
  OPENCLAW_GATEWAY_TOKEN   bearer token from a paired operator device
  DATABASE_URL             SQLAlchemy URL pointing at the same MC
                           Postgres the API process writes to

Slice-4-cleanup note: the worker deliberately does NOT import
``app.db.session`` (which loads ``app.core.config.settings`` at
import time and validates the FULL MC settings schema —
AUTH_MODE/LOCAL_AUTH_TOKEN/BASE_URL etc.). We construct our own
engine + session_maker from ``DATABASE_URL`` alone. Fail surface
shrinks to "DB unreachable", not "any of four pydantic validators
fails on unrelated HTTP-layer config".
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.env_file import load_env_file
from app.db.url import normalize_database_url
from app.services.mc_gateway_subscriber.db_session_state_projector import (
    DbSessionStateProjector,
)
from app.services.mc_gateway_subscriber.subscriber import Subscriber
from app.services.openclaw.protocol_constants import EVENT_SESSIONS_CHANGED

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE = "/etc/mc-gateway-subscriber/env"
DEFAULT_SUBSCRIPTIONS = ("sessions.subscribe",)


@dataclass(frozen=True)
class SubscriberConfig:
    url: str
    token: str
    database_url: str
    subscriptions: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS


def resolve_config(
    *,
    env_file_path: str = DEFAULT_ENV_FILE,
    subscriptions: Sequence[str] = DEFAULT_SUBSCRIPTIONS,
) -> SubscriberConfig:
    """Resolve URL + token + database_url from env-var-then-file. Exits
    on missing required keys with a targeted message naming each one."""
    file_cfg = load_env_file(env_file_path)
    url = os.environ.get("OPENCLAW_GATEWAY_WS_URL") or file_cfg.get("OPENCLAW_GATEWAY_WS_URL")
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or file_cfg.get("OPENCLAW_GATEWAY_TOKEN")
    database_url = os.environ.get("DATABASE_URL") or file_cfg.get("DATABASE_URL")
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
    if not database_url:
        raise SystemExit(
            "DATABASE_URL not set. Provide env var or write "
            f"DATABASE_URL=<value> to {env_file_path}. Use the same URL "
            "the MC API process writes to so the projector lands in the "
            "production gateway_session_state table."
        )
    return SubscriberConfig(
        url=url,
        token=token,
        database_url=database_url,
        subscriptions=tuple(subscriptions),
    )


def build_session_maker(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Construct a worker-private async session factory from a single
    URL. Uses the same ``pool_pre_ping`` and ``expire_on_commit=False``
    flags as the production engine so behaviour matches."""
    engine: AsyncEngine = create_async_engine(
        normalize_database_url(database_url),
        pool_pre_ping=True,
    )
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def run_async(stop: asyncio.Event, config: SubscriberConfig) -> None:
    """Construct a Subscriber and run until ``stop`` is set."""
    session_maker = build_session_maker(config.database_url)
    sub = Subscriber(
        url=config.url,
        token=config.token,
        subscriptions=config.subscriptions,
    )
    sub.on(
        EVENT_SESSIONS_CHANGED,
        DbSessionStateProjector(session_factory=session_maker),
    )
    await sub.run(stop)


def main() -> int:
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
