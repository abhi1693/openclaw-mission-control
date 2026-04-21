"""phase III: operator_decisions + operator_decision_task_links

Revision ID: b10ca1ab1e03
Revises: b10ca1ab1e02
Create Date: 2026-04-21 19:00:00.000000

Adds the two tables that back Phase III §I3 "operator decisions are
first-class":

- ``operator_decisions`` — one row per escalated decision the
  operator owns. Status moves from pending → resolved (with
  ``resolved_value``) or pending → cancelled.
- ``operator_decision_task_links`` — N:M join between decisions and
  the tasks they block. Unique per (decision_id, task_id) so one
  decision cannot double-link the same task.

Legacy ``Task.operator_decision_required`` / ``operator_decision_summary``
are preserved — this phase adds, it does not remove.

See docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I3.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b10ca1ab1e03"
down_revision = "b10ca1ab1e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("boards.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("unblock_rule", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("resolved_value", sa.Text(), nullable=True),
        sa.Column(
            "created_by_agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # Inline CHECK — op.create_check_constraint() after create_table
        # raises NotImplementedError on SQLite.
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'cancelled')",
            name="ck_operator_decisions_status_values",
        ),
    )
    # Clear the server default after table creation so the model is
    # the single source of truth for new rows.
    op.alter_column("operator_decisions", "status", server_default=None)
    # Partial index for the hot "pending decisions on this board"
    # dashboard lookup. Phase III inbox routing + the is_blocked
    # bridge both filter on status = 'pending'.
    op.create_index(
        "ix_operator_decisions_board_id_pending",
        "operator_decisions",
        ["board_id"],
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_operator_decisions_status",
        "operator_decisions",
        ["status"],
    )

    op.create_table(
        "operator_decision_task_links",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # decision_id indexed as prefix of the unique constraint below.
        sa.Column(
            "decision_id",
            sa.Uuid(),
            sa.ForeignKey("operator_decisions.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "decision_id",
            "task_id",
            name="uq_operator_decision_task_links_decision_id_task_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("operator_decision_task_links")
    op.drop_index(
        "ix_operator_decisions_status", table_name="operator_decisions"
    )
    op.drop_index(
        "ix_operator_decisions_board_id_pending",
        table_name="operator_decisions",
    )
    op.drop_table("operator_decisions")
