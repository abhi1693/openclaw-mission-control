"""Add disable_device_pairing setting to gateways.

Revision ID: c5d1a2b3e4f6
Revises: b7a1d9c3e4f5
Create Date: 2026-02-22 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c5d1a2b3e4f6"
down_revision = "b7a1d9c3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add gateway toggle to bypass device pairing handshake."""
    op.add_column(
        "gateways",
        sa.Column(
            "disable_device_pairing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("gateways", "disable_device_pairing", server_default=None)


def downgrade() -> None:
    """Remove gateway toggle to bypass device pairing handshake."""
    op.drop_column("gateways", "disable_device_pairing")
