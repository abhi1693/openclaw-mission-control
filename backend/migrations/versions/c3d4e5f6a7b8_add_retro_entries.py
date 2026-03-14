"""add retro_entries table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14 23:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retro_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("sprint_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("is_action_item", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recurrence", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("layer", sa.String(), nullable=True),
        sa.Column("nda_ref", sa.String(), nullable=True),
        sa.Column("resolved_sprint", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retro_entries_board_id", "retro_entries", ["board_id"])
    op.create_index("ix_retro_entries_sprint_id", "retro_entries", ["sprint_id"])
    op.create_index("ix_retro_entries_category", "retro_entries", ["category"])
    op.create_index("ix_retro_entries_author", "retro_entries", ["author"])
    op.create_index("ix_retro_entries_status", "retro_entries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_retro_entries_status", table_name="retro_entries")
    op.drop_index("ix_retro_entries_author", table_name="retro_entries")
    op.drop_index("ix_retro_entries_category", table_name="retro_entries")
    op.drop_index("ix_retro_entries_sprint_id", table_name="retro_entries")
    op.drop_index("ix_retro_entries_board_id", table_name="retro_entries")
    op.drop_table("retro_entries")
