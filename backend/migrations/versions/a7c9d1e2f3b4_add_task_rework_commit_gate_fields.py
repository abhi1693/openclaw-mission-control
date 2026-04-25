"""Add task rework commit gate field.

Revision ID: a7c9d1e2f3b4
Revises: e40f1a2b3c4d
Create Date: 2026-04-25 19:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7c9d1e2f3b4"
down_revision = "e40f1a2b3c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("rework_entry_commit_sha", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "rework_entry_commit_sha")
