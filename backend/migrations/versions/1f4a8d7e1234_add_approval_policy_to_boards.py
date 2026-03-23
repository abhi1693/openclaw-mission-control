"""add approval_policy to boards

Revision ID: 1f4a8d7e1234
Revises: 47bc9d8e1234
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "1f4a8d7e1234"
down_revision = "47bc9d8e1234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add boards.approval_policy column as nullable JSON."""
    op.add_column(
        "boards",
        sa.Column(
            "approval_policy",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove boards.approval_policy column."""
    op.drop_column("boards", "approval_policy")
