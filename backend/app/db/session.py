"""Database engine, session factory, and startup migration helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
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
    if scheme == "postgresql":
        return f"postgresql+psycopg://{rest}"
    return database_url


async_engine: AsyncEngine = create_async_engine(
    _normalize_database_url(settings.database_url),
    pool_pre_ping=True,
)
async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
logger = get_logger(__name__)


def _alembic_config() -> Config:
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.attributes["configure_logger"] = False
    return alembic_cfg


def run_migrations() -> None:
    """Apply Alembic migrations to the latest revision."""
    logger.info("Running database migrations.")
    command.upgrade(_alembic_config(), "head")
    logger.info("Database migrations complete.")


async def init_db() -> None:
    """Initialize database schema, running migrations when configured."""
    if settings.db_auto_migrate:
        versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
        if any(versions_dir.glob("*.py")):
            logger.info("Running migrations on startup")
            await asyncio.to_thread(run_migrations)
            return
        logger.warning("No migration revisions found; falling back to create_all")

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
