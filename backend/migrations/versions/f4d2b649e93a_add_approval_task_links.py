"""add approval task links

Revision ID: f4d2b649e93a
Revises: c3b58a391f2e
Create Date: 2026-02-11 20:05:00.000000

"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4d2b649e93a"
down_revision = "c3b58a391f2e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("approval_task_links"):
        op.create_table(
            "approval_task_links",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("approval_id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "approval_id",
                "task_id",
                name="uq_approval_task_links_approval_id_task_id",
            ),
        )
    else:
        target_unique_columns = ("approval_id", "task_id")
        unique_constraints = inspector.get_unique_constraints("approval_task_links")
        has_target_unique = False
        for item in unique_constraints:
            columns = tuple(item.get("column_names") or ())
            if columns == target_unique_columns:
                has_target_unique = True
                break
        if not has_target_unique:
            op.create_unique_constraint(
                "uq_approval_task_links_approval_id_task_id",
                "approval_task_links",
                ["approval_id", "task_id"],
            )

    indexes = inspector.get_indexes("approval_task_links")
    has_approval_id_index = any(
        tuple(item.get("column_names") or ()) == ("approval_id",) for item in indexes
    )
    has_task_id_index = any(tuple(item.get("column_names") or ()) == ("task_id",) for item in indexes)
    if not has_approval_id_index:
        op.create_index(
            op.f("ix_approval_task_links_approval_id"),
            "approval_task_links",
            ["approval_id"],
            unique=False,
        )
    if not has_task_id_index:
        op.create_index(
            op.f("ix_approval_task_links_task_id"),
            "approval_task_links",
            ["task_id"],
            unique=False,
        )

    link_table = sa.table(
        "approval_task_links",
        sa.column("id", sa.Uuid()),
        sa.column("approval_id", sa.Uuid()),
        sa.column("task_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime()),
    )
    approvals_table = sa.table(
        "approvals",
        sa.column("id", sa.Uuid()),
        sa.column("task_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime()),
    )
    rows = list(
        bind.execute(
            sa.select(
                approvals_table.c.id,
                approvals_table.c.task_id,
                approvals_table.c.created_at,
            )
            .select_from(approvals_table)
            .where(approvals_table.c.task_id.is_not(None)),
        ),
    )
    existing_links = {
        (approval_id, task_id)
        for approval_id, task_id in list(
            bind.execute(
                sa.select(
                    sa.column("approval_id"),
                    sa.column("task_id"),
                ).select_from(sa.table("approval_task_links")),
            ),
        )
    }
    missing_rows = [
        (approval_id, task_id, created_at)
        for approval_id, task_id, created_at in rows
        if (approval_id, task_id) not in existing_links
    ]
    if missing_rows:
        op.bulk_insert(
            link_table,
            [
                {
                    "id": uuid4(),
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "created_at": created_at,
                }
                for approval_id, task_id, created_at in missing_rows
            ],
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_approval_task_links_task_id"), table_name="approval_task_links")
    op.drop_index(op.f("ix_approval_task_links_approval_id"), table_name="approval_task_links")
    op.drop_table("approval_task_links")
