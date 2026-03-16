"""add agent_token_fast_hash for O(1) token lookup

Revision ID: d1e2f3a4b5c6
Revises: 99cd6df95f85
Create Date: 2026-03-15 20:40:00.000000

Adds agent_token_fast_hash: a SHA-256 hex digest of the raw token used as an
indexed lookup key so get_agent_auth_context can resolve a token with a single
indexed SELECT instead of loading every agent row and running PBKDF2 on each.

Backfill: existing agents have NULL fast_hash and fall through to the legacy
PBKDF2 scan path in agent_auth._find_agent_for_token. The slow path
automatically backfills the fast hash on first successful auth, so the system
self-heals without requiring manual token rotation. New tokens (minted after
this migration) always populate the column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("agent_token_fast_hash", sa.String(), nullable=True),
    )
    # Partial unique index: only enforce uniqueness where the value is present.
    # NULL values are excluded so legacy agents with NULL don't violate uniqueness.
    op.create_index(
        "ix_agents_agent_token_fast_hash",
        "agents",
        ["agent_token_fast_hash"],
        unique=True,
        postgresql_where=sa.text("agent_token_fast_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agents_agent_token_fast_hash", table_name="agents")
    op.drop_column("agents", "agent_token_fast_hash")
