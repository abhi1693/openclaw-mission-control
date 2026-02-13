"""add activity_events event_type created_at index

Revision ID: b05c7b628636
Revises: bbd5bbb26d97
Create Date: 2026-02-12 09:54:32.359256

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b05c7b628636'
down_revision = 'bbd5bbb26d97'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Speed activity feed/event filters that select by event_type and order by created_at.
    # Allows index scans (often backward) with LIMIT instead of bitmap+sort.
    op.create_index(
        "ix_activity_events_event_type_created_at",
        "activity_events",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_events_event_type_created_at", table_name="activity_events")
