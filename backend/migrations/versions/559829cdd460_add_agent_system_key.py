"""add agent system_key

Revision ID: 559829cdd460
Revises: a9b1c2d3e4f7
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "559829cdd460"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("system_key", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_agents_system_key",
        "agents",
        ["system_key"],
    )
    op.create_index(
        op.f("ix_agents_system_key"),
        "agents",
        ["system_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_system_key"), table_name="agents")
    op.drop_constraint("uq_agents_system_key", "agents", type_="unique")
    op.drop_column("agents", "system_key")

