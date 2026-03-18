"""Database engine, session factory, and startup helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app import models as _models
from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Import model modules so SQLModel metadata is fully registered at startup.
_MODEL_REGISTRY = _models


def _normalize_database_url(database_url: str) -> str:
    if "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    if scheme in ("postgresql", "postgres"):
        return f"postgresql+psycopg://{rest}"
    return database_url


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create parent directory for SQLite database file if needed."""
    if "sqlite" not in database_url:
        return
    # Extract path from URL like sqlite+aiosqlite:///./data/mission-control.db
    parts = database_url.split("///", 1)
    if len(parts) < 2:
        return
    db_path = Path(parts[1])
    if not db_path.is_absolute():
        db_path = Path(os.getcwd()) / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


normalized_url = _normalize_database_url(settings.database_url)
_ensure_sqlite_dir(normalized_url)

# SQLite doesn't support pool_pre_ping the same way; use simpler config
_is_sqlite = "sqlite" in normalized_url
_engine_kwargs: dict = {}
if not _is_sqlite:
    _engine_kwargs["pool_pre_ping"] = True

async_engine: AsyncEngine = create_async_engine(
    normalized_url,
    **_engine_kwargs,
)
async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
logger = get_logger(__name__)


async def init_db() -> None:
    """Initialize database schema using create_all (SQLite) or migrations (PostgreSQL)."""
    if _is_sqlite:
        # For SQLite, just create all tables directly — no Alembic migrations needed.
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("db.init.sqlite create_all complete")
        return

    # For PostgreSQL (if ever used), run Alembic migrations.
    if settings.db_auto_migrate:
        import asyncio

        from alembic import command
        from alembic.config import Config

        alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.attributes["configure_logger"] = False
        logger.info("Running database migrations on startup")
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        logger.info("Database migrations complete.")
        return

    async with async_engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async DB session with safe rollback on errors."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            in_txn = False
            try:
                in_txn = bool(session.in_transaction())
            except SQLAlchemyError:
                logger.exception("Failed to inspect session transaction state.")
            if in_txn:
                try:
                    await session.rollback()
                except SQLAlchemyError:
                    logger.exception("Failed to rollback session after request error.")
