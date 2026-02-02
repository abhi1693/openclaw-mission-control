"""add reply_to_comment_id to task_comments

Revision ID: 9d3d9b9c1a23
Revises: 157587037601
Create Date: 2026-02-02 08:15:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9d3d9b9c1a23"
down_revision = "157587037601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_comments", sa.Column("reply_to_comment_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_task_comments_reply_to_comment_id",
        "task_comments",
        "task_comments",
        ["reply_to_comment_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_task_comments_reply_to_comment_id", "task_comments", type_="foreignkey")
    op.drop_column("task_comments", "reply_to_comment_id")
