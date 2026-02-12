"""add composite indexes for task listing

Revision ID: b4338be78eec
Revises: f4d2b649e93a
Create Date: 2026-02-12 07:54:27.450391

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4338be78eec'
down_revision = 'f4d2b649e93a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Task list endpoints filter primarily by board_id, optionally by status
    # and assigned_agent_id, and always order by created_at (desc in code).
    # These composite btree indexes allow fast backward scans with LIMIT.
    op.create_index(
        "ix_tasks_board_id_created_at",
        "tasks",
        ["board_id", "created_at"],
    )
    op.create_index(
        "ix_tasks_board_id_status_created_at",
        "tasks",
        ["board_id", "status", "created_at"],
    )
    op.create_index(
        "ix_tasks_board_id_assigned_agent_id_created_at",
        "tasks",
        ["board_id", "assigned_agent_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_board_id_assigned_agent_id_created_at", table_name="tasks")
    op.drop_index("ix_tasks_board_id_status_created_at", table_name="tasks")
    op.drop_index("ix_tasks_board_id_created_at", table_name="tasks")
