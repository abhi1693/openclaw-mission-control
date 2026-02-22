"""Add allow_insecure_tls field to gateways.

Revision ID: 2f3e4a5b6c7d
Revises: 1a7b2c3d4e5f
Create Date: 2026-02-22 05:30:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "2f3e4a5b6c7d"
down_revision = "1a7b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add gateways.allow_insecure_tls column with default False."""
    op.add_column(
        "gateways",
        sa.Column(
            "allow_insecure_tls",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("gateways", "allow_insecure_tls", server_default=None)


def downgrade() -> None:
    """Remove gateways.allow_insecure_tls column."""
    op.drop_column("gateways", "allow_insecure_tls")
