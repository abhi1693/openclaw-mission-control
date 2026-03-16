"""make approval confidence float

Revision ID: e2f9c6b4a1d3
Revises: d8c1e5a4f7b2
Create Date: 2026-02-12 20:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f9c6b4a1d3"
down_revision = "d8c1e5a4f7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "approvals",
        "confidence",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "approvals",
        "confidence",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
