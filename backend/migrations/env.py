"""Alembic environment configuration for backend database migrations."""

from __future__ import annotations

import importlib
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

importlib.import_module("app.models")
settings = importlib.import_module("app.core.config").settings

config = context.config
configure_logger = config.attributes.get("configure_logger", True)

if config.config_file_name is not None and configure_logger:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _normalize_database_url(database_url: str) -> str:
    if "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    if scheme in ("postgresql", "postgres"):
        return f"postgresql+psycopg://{rest}"
    return database_url


def get_url() -> str:
    """Return the normalized SQLAlchemy database URL for Alembic."""
    return _normalize_database_url(settings.database_url)


config.set_main_option("sqlalchemy.url", get_url())


def run_migrations_offline() -> None:
    """Run migrations in offline mode without DB engine connectivity."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode using a live DB connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
