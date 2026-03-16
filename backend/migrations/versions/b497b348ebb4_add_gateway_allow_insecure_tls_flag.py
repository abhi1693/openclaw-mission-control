"""Add allow_insecure_tls field to gateways.

Revision ID: b497b348ebb4
Revises: c5d1a2b3e4f6
Create Date: 2026-02-22 20:06:54.417968

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b497b348ebb4"
down_revision = "c5d1a2b3e4f6"
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
