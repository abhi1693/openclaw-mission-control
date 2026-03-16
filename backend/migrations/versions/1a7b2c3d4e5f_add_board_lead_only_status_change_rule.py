"""add lead-only status change board rule

Revision ID: 1a7b2c3d4e5f
Revises: c2e9f1a6d4b8
Create Date: 2026-02-13 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1a7b2c3d4e5f"
down_revision = "fa6e83f8d9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "only_lead_can_change_status" not in board_columns:
        op.add_column(
            "boards",
            sa.Column(
                "only_lead_can_change_status",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "only_lead_can_change_status" in board_columns:
        op.drop_column("boards", "only_lead_can_change_status")
