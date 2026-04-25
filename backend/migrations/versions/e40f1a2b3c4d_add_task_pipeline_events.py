"""add task pipeline events

Revision ID: e40f1a2b3c4d
Revises: d30eab11ad03
Create Date: 2026-04-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e40f1a2b3c4d"
down_revision = "d30eab11ad03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_pipeline_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("artifact_hash", sa.String(), nullable=True),
        sa.Column("deploy_target", sa.String(), nullable=True),
        sa.Column("live_sha", sa.String(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_task_pipeline_events_agent_id"),
        "task_pipeline_events",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_board_id"),
        "task_pipeline_events",
        ["board_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_commit_sha"),
        "task_pipeline_events",
        ["commit_sha"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_created_at"),
        "task_pipeline_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_source"),
        "task_pipeline_events",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_state"),
        "task_pipeline_events",
        ["state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pipeline_events_task_id"),
        "task_pipeline_events",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_pipeline_events_task_state_created_at",
        "task_pipeline_events",
        ["task_id", "state", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_pipeline_events_task_state_created_at", table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_task_id"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_state"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_source"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_created_at"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_commit_sha"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_board_id"), table_name="task_pipeline_events")
    op.drop_index(op.f("ix_task_pipeline_events_agent_id"), table_name="task_pipeline_events")
    op.drop_table("task_pipeline_events")
