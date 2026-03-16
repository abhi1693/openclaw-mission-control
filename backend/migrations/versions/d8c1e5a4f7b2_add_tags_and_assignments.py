"""add tags and tag assignments

Revision ID: d8c1e5a4f7b2
Revises: 99cd6df95f85, b4338be78eec
Create Date: 2026-02-12 16:05:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d8c1e5a4f7b2"
down_revision = ("99cd6df95f85", "b4338be78eec")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("tags"):
        op.create_table(
            "tags",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("color", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "slug",
                name="uq_tags_organization_id_slug",
            ),
        )
    tag_indexes = {item.get("name") for item in inspector.get_indexes("tags")}
    if op.f("ix_tags_organization_id") not in tag_indexes:
        op.create_index(
            op.f("ix_tags_organization_id"),
            "tags",
            ["organization_id"],
            unique=False,
        )
    if op.f("ix_tags_slug") not in tag_indexes:
        op.create_index(
            op.f("ix_tags_slug"),
            "tags",
            ["slug"],
            unique=False,
        )

    if not inspector.has_table("tag_assignments"):
        op.create_table(
            "tag_assignments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("tag_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "tag_id",
                name="uq_tag_assignments_task_id_tag_id",
            ),
        )
    assignment_indexes = {
        item.get("name") for item in inspector.get_indexes("tag_assignments")
    }
    if op.f("ix_tag_assignments_task_id") not in assignment_indexes:
        op.create_index(
            op.f("ix_tag_assignments_task_id"),
            "tag_assignments",
            ["task_id"],
            unique=False,
        )
    if op.f("ix_tag_assignments_tag_id") not in assignment_indexes:
        op.create_index(
            op.f("ix_tag_assignments_tag_id"),
            "tag_assignments",
            ["tag_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_tag_assignments_tag_id"), table_name="tag_assignments")
    op.drop_index(op.f("ix_tag_assignments_task_id"), table_name="tag_assignments")
    op.drop_table("tag_assignments")
    op.drop_index(op.f("ix_tags_slug"), table_name="tags")
    op.drop_index(op.f("ix_tags_organization_id"), table_name="tags")
    op.drop_table("tags")
