"""Add last_heartbeat_at and agent_token_prefix to agents table.

last_heartbeat_at: timestamp of the most recent successful POST /api/v1/agent/heartbeat.
  Replaces the fixed OFFLINE_AFTER time-window with a per-agent 1.5× interval threshold.
  NULL rows fall back to last_seen_at + fixed 10m for backward compatibility.

agent_token_prefix: first 8 chars of the raw token stored at creation/rotation time.
  Enables O(1) DB pre-filter before PBKDF2 in _find_agent_for_token(), eliminating the
  O(N × PBKDF2) linear scan that becomes an auth latency blocker at 100+ agents.
  NULL for pre-migration agents; those fall back to the linear scan until re-keyed.

Revision ID: c7e4f2a9b1d3
Revises: a9b1c2d3e4f7
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7e4f2a9b1d3"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    agent_columns = {col["name"] for col in inspector.get_columns("agents")}
    agent_indexes = {idx["name"] for idx in inspector.get_indexes("agents")}

    if "last_heartbeat_at" not in agent_columns:
        op.add_column(
            "agents",
            sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        )

    if "agent_token_prefix" not in agent_columns:
        op.add_column(
            "agents",
            sa.Column("agent_token_prefix", sa.String(length=8), nullable=True),
        )

    if "ix_agents_agent_token_prefix" not in agent_indexes:
        op.create_index(
            "ix_agents_agent_token_prefix",
            "agents",
            ["agent_token_prefix"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    agent_columns = {col["name"] for col in inspector.get_columns("agents")}
    agent_indexes = {idx["name"] for idx in inspector.get_indexes("agents")}

    if "ix_agents_agent_token_prefix" in agent_indexes:
        op.drop_index("ix_agents_agent_token_prefix", table_name="agents")
    if "agent_token_prefix" in agent_columns:
        op.drop_column("agents", "agent_token_prefix")
    if "last_heartbeat_at" in agent_columns:
        op.drop_column("agents", "last_heartbeat_at")
