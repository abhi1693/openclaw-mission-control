"""Add description field to boards.

Revision ID: c3b58a391f2e
Revises: b308f2876359
Create Date: 2026-02-11 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3b58a391f2e"
down_revision = "b308f2876359"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add required board description column."""
    op.add_column(
        "boards",
        sa.Column(
            "description",
            sa.String(),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("boards", "description", server_default=None)


def downgrade() -> None:
    """Remove board description column."""
    op.drop_column("boards", "description")
