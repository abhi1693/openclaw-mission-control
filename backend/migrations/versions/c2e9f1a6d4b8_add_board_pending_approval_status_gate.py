"""add board rule toggles

Revision ID: c2e9f1a6d4b8
Revises: e2f9c6b4a1d3
Create Date: 2026-02-12 23:55:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2e9f1a6d4b8"
down_revision = "e2f9c6b4a1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column(
            "require_approval_for_done",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "require_review_before_done",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "block_status_changes_with_pending_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("boards", "block_status_changes_with_pending_approval")
    op.drop_column("boards", "require_review_before_done")
    op.drop_column("boards", "require_approval_for_done")
