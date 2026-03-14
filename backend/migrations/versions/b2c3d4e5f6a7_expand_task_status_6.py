"""expand task status from 4 to 6 values

Revision ID: b2c3d4e5f6a7
Revises: a9b1c2d3e4f7
Create Date: 2026-03-14 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The `tasks.status` column is a plain VARCHAR/TEXT — no DB-level enum constraint.
    # New allowed values: inbox, todo, in_progress, in_review, sprint_done, done.
    #
    # Migrate existing "review" data to "in_review".
    op.execute(
        sa.text("UPDATE tasks SET status = 'in_review' WHERE status = 'review'")
    )


def downgrade() -> None:
    # Revert "in_review" back to "review" for backward compatibility.
    op.execute(
        sa.text("UPDATE tasks SET status = 'review' WHERE status = 'in_review'")
    )
    # Note: "todo" and "sprint_done" rows would need manual handling if they exist.
    # This is a best-effort downgrade.
    op.execute(
        sa.text("UPDATE tasks SET status = 'inbox' WHERE status = 'todo'")
    )
    op.execute(
        sa.text("UPDATE tasks SET status = 'done' WHERE status = 'sprint_done'")
    )
