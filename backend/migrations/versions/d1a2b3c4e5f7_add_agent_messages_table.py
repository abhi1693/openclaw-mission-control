"""Add agent_messages table for inter-agent communication.

Revision ID: d1a2b3c4e5f7
Revises: a9b1c2d3e4f7
Create Date: 2026-03-16 03:55:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d1a2b3c4e5f7"
down_revision: str = "a9b1c2d3e4f7"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("sender_agent_id", sa.Uuid(), nullable=False),
        sa.Column("receiver_agent_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["sender_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["receiver_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_messages_board_id"),
        "agent_messages",
        ["board_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_messages_sender_agent_id"),
        "agent_messages",
        ["sender_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_messages_receiver_agent_id"),
        "agent_messages",
        ["receiver_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_messages_task_id"),
        "agent_messages",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_messages_board_id_created_at",
        "agent_messages",
        ["board_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_messages_board_id_created_at", table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_task_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_receiver_agent_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_sender_agent_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_board_id"), table_name="agent_messages")
    op.drop_table("agent_messages")
