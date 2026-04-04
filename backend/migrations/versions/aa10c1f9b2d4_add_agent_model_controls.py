"""Add agent model controls tables.

Revision ID: 001_add_agent_model_controls
Revises: (set to latest head in target repo)
Create Date: 2026-03-28

Tables added:
  - agent_model_profiles
  - agent_model_fallback_entries
  - agent_model_recommendation_runs
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa10c1f9b2d4"
down_revision: Union[str, None] = "a9b1c2d3e4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # agent_model_profiles
    # -----------------------------------------------------------------------
    op.create_table(
        "agent_model_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=True),
        sa.Column("role_key", sa.Text(), nullable=False, server_default="worker"),
        # Primary selection — admin intent
        sa.Column("primary_model_id", sa.Text(), nullable=True),
        sa.Column(
            "primary_selection_mode",
            sa.Text(),
            nullable=False,
            server_default="auto",
        ),
        # Recommendation state — system generated
        sa.Column("recommended_primary_model_id", sa.Text(), nullable=True),
        sa.Column(
            "recommendation_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("recommendation_generated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("recommendation_version", sa.Text(), nullable=True),
        sa.Column("recommendation_explanation", sa.JSON(), nullable=True),
        # Fallback override — admin intent
        sa.Column(
            "fallback_override_mode",
            sa.Text(),
            nullable=False,
            server_default="none",
        ),
        sa.Column("fallback_override_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Materialized effective config
        sa.Column("effective_primary_model_id", sa.Text(), nullable=True),
        sa.Column("effective_fallback_policy_version", sa.Text(), nullable=True),
        sa.Column("effective_config_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Validation
        sa.Column(
            "config_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "primary_selection_mode IN ('manual', 'auto')",
            name="ck_agent_model_profiles_primary_selection_mode",
        ),
        sa.CheckConstraint(
            "fallback_override_mode IN ('none', 'append', 'replace')",
            name="ck_agent_model_profiles_fallback_override_mode",
        ),
        sa.CheckConstraint(
            "recommendation_status IN ('fresh', 'stale', 'error', 'pending')",
            name="ck_agent_model_profiles_recommendation_status",
        ),
        sa.CheckConstraint(
            "config_status IN ('valid', 'stale', 'degraded', 'invalid', 'pending')",
            name="ck_agent_model_profiles_config_status",
        ),
    )
    op.create_index("ix_agent_model_profiles_agent_id", "agent_model_profiles", ["agent_id"], unique=True)
    op.create_index("ix_agent_model_profiles_board_id", "agent_model_profiles", ["board_id"])

    # -----------------------------------------------------------------------
    # agent_model_fallback_entries
    # -----------------------------------------------------------------------
    op.create_table(
        "agent_model_fallback_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_model_profile_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.Text(), nullable=False, server_default="unavailable"),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("generation_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_model_profile_id"],
            ["agent_model_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source IN ('generated', 'manual')",
            name="ck_agent_model_fallback_entries_source",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_agent_model_fallback_entries_position_non_negative",
        ),
        sa.UniqueConstraint(
            "agent_model_profile_id",
            "source",
            "position",
            name="uq_agent_model_fallback_entries_profile_source_position",
        ),
    )
    op.create_index(
        "ix_agent_model_fallback_entries_profile_id",
        "agent_model_fallback_entries",
        ["agent_model_profile_id"],
    )

    # -----------------------------------------------------------------------
    # agent_model_recommendation_runs
    # -----------------------------------------------------------------------
    op.create_table(
        "agent_model_recommendation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=True),
        sa.Column("role_key", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("policy_version", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("recommended_primary_model_id", sa.Text(), nullable=True),
        sa.Column("fallback_plan", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.JSON(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'error')",
            name="ck_agent_model_recommendation_runs_status",
        ),
    )
    op.create_index(
        "ix_agent_model_recommendation_runs_agent_id",
        "agent_model_recommendation_runs",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_model_recommendation_runs_generated_at",
        "agent_model_recommendation_runs",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_model_recommendation_runs")
    op.drop_table("agent_model_fallback_entries")
    op.drop_table("agent_model_profiles")
