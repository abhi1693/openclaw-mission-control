"""Add gateway_model_profile_defaults table.

Revision ID: bb20d2e1c3f5
Revises: aa10c1f9b2d4
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "bb20d2e1c3f5"
down_revision = "aa10c1f9b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_model_profile_defaults",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "gateway_id",
            sa.Uuid(),
            sa.ForeignKey("gateways.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("general_model_id", sa.String(), nullable=True),
        sa.Column("coder_model_id", sa.String(), nullable=True),
        sa.Column("budget_model_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("gateway_model_profile_defaults")
