"""Add agent lifecycle metadata columns.

Revision ID: e3a1b2c4d5f6
Revises: b497b348ebb4
Create Date: 2026-02-24 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "e3a1b2c4d5f6"
down_revision = "b497b348ebb4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add lifecycle generation, wake tracking, and failure metadata."""
    op.add_column(
        "agents",
        sa.Column("lifecycle_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agents",
        sa.Column("wake_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("agents", sa.Column("last_wake_sent_at", sa.DateTime(), nullable=True))
    op.add_column("agents", sa.Column("checkin_deadline_at", sa.DateTime(), nullable=True))
    op.add_column("agents", sa.Column("last_provision_error", sa.Text(), nullable=True))
    op.alter_column("agents", "lifecycle_generation", server_default=None)
    op.alter_column("agents", "wake_attempts", server_default=None)


def downgrade() -> None:
    """Remove lifecycle generation, wake tracking, and failure metadata."""
    op.drop_column("agents", "last_provision_error")
    op.drop_column("agents", "checkin_deadline_at")
    op.drop_column("agents", "last_wake_sent_at")
    op.drop_column("agents", "wake_attempts")
    op.drop_column("agents", "lifecycle_generation")

