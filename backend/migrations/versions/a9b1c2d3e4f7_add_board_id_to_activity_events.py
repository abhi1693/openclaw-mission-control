"""add board_id to activity_events

Revision ID: a9b1c2d3e4f7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-04 18:20:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9b1c2d3e4f7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_events", sa.Column("board_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE activity_events AS ae
        SET board_id = t.board_id
        FROM tasks AS t
        WHERE ae.task_id = t.id
          AND ae.board_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE activity_events AS ae
        SET board_id = a.board_id
        FROM agents AS a
        WHERE ae.agent_id = a.id
          AND ae.board_id IS NULL
          AND a.board_id IS NOT NULL
        """
    )
    op.create_foreign_key(
        "fk_activity_events_board_id_boards",
        "activity_events",
        "boards",
        ["board_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_activity_events_board_id"),
        "activity_events",
        ["board_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_activity_events_board_id"), table_name="activity_events")
    op.drop_constraint(
        "fk_activity_events_board_id_boards",
        "activity_events",
        type_="foreignkey",
    )
    op.drop_column("activity_events", "board_id")
