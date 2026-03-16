"""Add max_agents field to boards.

Revision ID: 4c1f5e2a7b9d
Revises: c9d7e9b6a4f2
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4c1f5e2a7b9d"
down_revision = "c9d7e9b6a4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add required boards.max_agents column with a safe backfill default."""
    op.add_column(
        "boards",
        sa.Column(
            "max_agents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.alter_column("boards", "max_agents", server_default=None)


def downgrade() -> None:
    """Remove boards.max_agents column."""
    op.drop_column("boards", "max_agents")
