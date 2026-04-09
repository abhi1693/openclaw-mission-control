"""add auto heartbeat governor schema

Revision ID: e474bac07e41
Revises: a9b1c2d3e4f7
Create Date: 2026-03-08 00:23:13.457926

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e474bac07e41"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "auto_heartbeat_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "auto_heartbeat_step",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "auto_heartbeat_off",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column("auto_heartbeat_last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_agents_auto_heartbeat_enabled"),
        "agents",
        ["auto_heartbeat_enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agents_auto_heartbeat_off"),
        "agents",
        ["auto_heartbeat_off"],
        unique=False,
    )
    op.alter_column("agents", "auto_heartbeat_enabled", server_default=None)
    op.alter_column("agents", "auto_heartbeat_step", server_default=None)
    op.alter_column("agents", "auto_heartbeat_off", server_default=None)

    op.add_column(
        "boards",
        sa.Column(
            "auto_heartbeat_governor_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "auto_heartbeat_governor_ladder",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"10m\", \"30m\", \"1h\", \"3h\", \"6h\"]'"),
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "auto_heartbeat_governor_lead_cap_every",
            sa.String(),
            nullable=False,
            server_default="1h",
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "auto_heartbeat_governor_activity_trigger_type",
            sa.String(),
            nullable=False,
            server_default="B",
        ),
    )
    op.alter_column("boards", "auto_heartbeat_governor_enabled", server_default=None)
    op.alter_column("boards", "auto_heartbeat_governor_ladder", server_default=None)
    op.alter_column("boards", "auto_heartbeat_governor_lead_cap_every", server_default=None)
    op.alter_column("boards", "auto_heartbeat_governor_activity_trigger_type", server_default=None)


def downgrade() -> None:
    op.drop_column("boards", "auto_heartbeat_governor_activity_trigger_type")
    op.drop_column("boards", "auto_heartbeat_governor_lead_cap_every")
    op.drop_column("boards", "auto_heartbeat_governor_ladder")
    op.drop_column("boards", "auto_heartbeat_governor_enabled")

    op.drop_index(op.f("ix_agents_auto_heartbeat_off"), table_name="agents")
    op.drop_index(op.f("ix_agents_auto_heartbeat_enabled"), table_name="agents")
    op.drop_column("agents", "auto_heartbeat_last_active_at")
    op.drop_column("agents", "auto_heartbeat_off")
    op.drop_column("agents", "auto_heartbeat_step")
    op.drop_column("agents", "auto_heartbeat_enabled")
