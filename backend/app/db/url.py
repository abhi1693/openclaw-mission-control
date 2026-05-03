"""URL normalization for SQLAlchemy database URLs.

Standalone module — no ``app.core.config`` import — so the long-lived
``mc_gateway_subscriber`` worker can construct its own engine from
``DATABASE_URL`` alone without dragging in MC's full pydantic settings
schema (and the four-key validation cascade that comes with it).

The production engine factory in ``app.db.session`` imports this same
helper, so the worker's URL handling stays in lockstep with the API
process — no drift risk from duplicating the rule.
"""

from __future__ import annotations


def normalize_database_url(database_url: str) -> str:
    """Map plain ``postgresql://`` / ``postgres://`` URLs to the
    asyncio-capable ``postgresql+psycopg://`` form. Other schemes
    (``sqlite+aiosqlite``, etc.) pass through unchanged."""
    if "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    if scheme in ("postgresql", "postgres"):
        return f"postgresql+psycopg://{rest}"
    return database_url
