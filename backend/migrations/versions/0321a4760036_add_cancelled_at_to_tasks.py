"""add_cancelled_at_to_tasks

Revision ID: 0321a4760036
Revises: a9b1c2d3e4f7
Create Date: 2026-04-08 15:11:12.774545

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0321a4760036'
down_revision = 'a9b1c2d3e4f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("cancelled_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "cancelled_at")
