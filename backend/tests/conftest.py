# ruff: noqa: INP001
"""Pytest configuration shared across backend tests."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tests should fail fast if auth-mode wiring breaks, but still need deterministic
# defaults during import-time settings initialization, regardless of shell env.
os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"

# ---------------------------------------------------------------
# Shared in-memory SQLite fixtures
#
# New tests should consume these instead of hand-rolling an engine +
# session + SQLModel.metadata.create_all block. Legacy tests keep
# their inline fixtures — lazy migration, not a churn commit.
# ---------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    """Fresh in-memory SQLite engine with SQLModel metadata applied.

    ``:memory:`` is per-connection on sqlite so isolation is automatic;
    dispose tears the connection pool down explicitly for cleanliness.
    """

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_session(sqlite_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """AsyncSession bound to :func:`sqlite_engine`.

    ``expire_on_commit=False`` matches the production session factory
    so tests can read back an object after the commit that created it.
    """

    session = AsyncSession(sqlite_engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
