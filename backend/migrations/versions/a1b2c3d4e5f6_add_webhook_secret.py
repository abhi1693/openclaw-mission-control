"""Add secret and signature_header columns to board_webhooks for HMAC verification.

Revision ID: a1b2c3d4e5f6
Revises: f1b2c3d4e5a6
Create Date: 2026-03-03 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f1b2c3d4e5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add secret and signature_header columns to board_webhooks table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("board_webhooks")}
    if "secret" not in columns:
        op.add_column(
            "board_webhooks",
            sa.Column("secret", sa.String(), nullable=True),
        )
    if "signature_header" not in columns:
        op.add_column(
            "board_webhooks",
            sa.Column("signature_header", sa.String(), nullable=True),
        )


def downgrade() -> None:
    """Remove secret and signature_header columns from board_webhooks table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("board_webhooks")}
    if "signature_header" in columns:
        op.drop_column("board_webhooks", "signature_header")
    if "secret" in columns:
        op.drop_column("board_webhooks", "secret")
