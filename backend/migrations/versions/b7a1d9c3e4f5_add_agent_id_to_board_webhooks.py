"""Add optional agent mapping to board webhooks.

Revision ID: b7a1d9c3e4f5
Revises: a2f6c9d4b7e8
Create Date: 2026-02-15 14:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b7a1d9c3e4f5"
down_revision = "a2f6c9d4b7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add optional mapped agent reference on board webhooks."""
    op.add_column("board_webhooks", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.create_index("ix_board_webhooks_agent_id", "board_webhooks", ["agent_id"], unique=False)
    op.create_foreign_key(
        "fk_board_webhooks_agent_id_agents",
        "board_webhooks",
        "agents",
        ["agent_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove optional mapped agent reference from board webhooks."""
    op.drop_constraint("fk_board_webhooks_agent_id_agents", "board_webhooks", type_="foreignkey")
    op.drop_index("ix_board_webhooks_agent_id", table_name="board_webhooks")
    op.drop_column("board_webhooks", "agent_id")
