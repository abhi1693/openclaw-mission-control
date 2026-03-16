"""Track prior in_progress_at during status transitions.

Revision ID: a2f6c9d4b7e8
Revises: 4c1f5e2a7b9d
Create Date: 2026-02-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a2f6c9d4b7e8"
down_revision = "4c1f5e2a7b9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add previous_in_progress_at column to tasks."""
    op.add_column(
        "tasks",
        sa.Column("previous_in_progress_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Drop previous_in_progress_at column from tasks."""
    op.drop_column("tasks", "previous_in_progress_at")
