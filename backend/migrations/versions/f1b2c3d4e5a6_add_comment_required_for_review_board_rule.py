"""add comment-required-for-review board rule

Revision ID: f1b2c3d4e5a6
Revises: e3a1b2c4d5f6
Create Date: 2026-02-25 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "f1b2c3d4e5a6"
down_revision = "e3a1b2c4d5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "comment_required_for_review" not in board_columns:
        op.add_column(
            "boards",
            sa.Column(
                "comment_required_for_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "comment_required_for_review" in board_columns:
        op.drop_column("boards", "comment_required_for_review")
