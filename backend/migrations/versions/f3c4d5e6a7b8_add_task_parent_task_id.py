"""add parent_task_id to tasks for decomposition cascade

Phase V — parent_task_id closes the propagation gap where a child task
created during decomposition outlives its reason-for-being. Once a
parent reaches a terminal state (done/cancelled), the lead next-action
gate can surface non-terminal children for cleanup, and a narrow
lead-cancel exception (follow-up PR) lets the lead retire them
without operator intervention.

The relationship is purely structural — it does not duplicate
``TaskDependency`` (which encodes ordering, not parent/child
containment). A single task can be both a parent of subtasks and a
dependency of another phase; those concerns are independent.

Additive, nullable, no backfill. Pre-existing decomposition pairs that
were tracked only in comments stay implicit; new ones get the
explicit link via ``lead-inbox-routing``.

ON DELETE SET NULL — when a parent row is hard-deleted, children
become orphaned-without-parent (the more common path is parent moves
to cancelled, which preserves the link).

Revision ID: f3c4d5e6a7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-05-01 13:50:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "f3c4d5e6a7b8"
down_revision = "f2b3c4d5e6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "parent_task_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_tasks_parent_task_id_tasks",
        "tasks",
        "tasks",
        ["parent_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tasks_parent_task_id",
        "tasks",
        ["parent_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_constraint("fk_tasks_parent_task_id_tasks", "tasks", type_="foreignkey")
    op.drop_column("tasks", "parent_task_id")
