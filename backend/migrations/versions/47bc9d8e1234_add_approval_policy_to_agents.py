"""add approval_policy to agents

Revision ID: 47bc9d8e1234
Revises: a9b1c2d3e4f7
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "47bc9d8e1234"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agents.approval_policy column as nullable JSON."""
    op.add_column(
        "agents",
        sa.Column(
            "approval_policy",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove agents.approval_policy column."""
    op.drop_column("agents", "approval_policy")
