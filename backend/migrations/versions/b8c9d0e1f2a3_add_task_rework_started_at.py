"""Add durable task rework marker.

Revision ID: b8c9d0e1f2a3
Revises: a7c9d1e2f3b4
Create Date: 2026-04-25 19:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a7c9d1e2f3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("rework_started_at", sa.DateTime(), nullable=True))
    op.create_index("ix_tasks_rework_started_at", "tasks", ["rework_started_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_rework_started_at", table_name="tasks")
    op.drop_column("tasks", "rework_started_at")
