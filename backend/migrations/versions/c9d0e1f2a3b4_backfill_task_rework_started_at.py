"""Backfill durable task rework markers.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-25 19:45:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tasks
        SET
            rework_started_at = COALESCE(
                (
                    SELECT MAX(activity_events.created_at)
                    FROM activity_events
                    WHERE activity_events.task_id = tasks.id
                      AND activity_events.event_type = 'task.status_changed'
                      AND activity_events.message LIKE 'Task moved to rework:%'
                ),
                tasks.updated_at
            ),
            rework_entry_commit_sha = COALESCE(rework_entry_commit_sha, packet_commit_sha)
        WHERE status = 'rework'
          AND rework_started_at IS NULL
        """
    )


def downgrade() -> None:
    pass
