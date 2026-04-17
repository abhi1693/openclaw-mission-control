"""add agent_heartbeat_repair_events table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-17 14:30:00.000000

Append-only forensic log for the I7 heartbeat watchdog. Each row records
the state of an agent at the moment the watchdog repaired a null
``checkin_deadline_at`` while the agent was ``status='online'``. This
preserves diagnostic evidence that would otherwise be erased by the
repair itself.

See docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md
section A.1 (failure mode F1).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_heartbeat_repair_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column("prev_deadline", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("wake_attempts", sa.Integer(), nullable=False),
        sa.Column("elapsed_since_last_seen_seconds", sa.Float(), nullable=True),
        sa.Column("repair_reason", sa.String(), nullable=False),
        sa.Column("new_deadline", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        op.f("ix_agent_heartbeat_repair_events_agent_id"),
        "agent_heartbeat_repair_events",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_heartbeat_repair_events_repair_reason"),
        "agent_heartbeat_repair_events",
        ["repair_reason"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_heartbeat_repair_events_created_at"),
        "agent_heartbeat_repair_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_heartbeat_repair_events_created_at"),
        table_name="agent_heartbeat_repair_events",
    )
    op.drop_index(
        op.f("ix_agent_heartbeat_repair_events_repair_reason"),
        table_name="agent_heartbeat_repair_events",
    )
    op.drop_index(
        op.f("ix_agent_heartbeat_repair_events_agent_id"),
        table_name="agent_heartbeat_repair_events",
    )
    op.drop_table("agent_heartbeat_repair_events")
