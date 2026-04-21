"""phase II: structured blocker sidecar table

Revision ID: b10ca1ab1e00
Revises: e5f6a7b8c9d0
Create Date: 2026-04-21 16:00:00.000000

Adds the ``blockers`` table — Phase II §I1's first-class routing
object. Tasks flagged as blocked must now carry at least one open
Blocker row; free-text "blocked on ..." comments become a protocol
error in Phase VI once lane quieting is wired up.

See docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I1 and
§"Phase II — Blocker and review sidecars".
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b10ca1ab1e00"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blockers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("boards.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("owner_role", sa.String(length=64), nullable=False),
        sa.Column("required_artifact", sa.Text(), nullable=True),
        sa.Column("target_env", sa.String(length=64), nullable=True),
        sa.Column("reopen_condition", sa.Text(), nullable=True),
        sa.Column(
            "created_by_agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by_agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supersedes_blocker_id",
            sa.Uuid(),
            sa.ForeignKey("blockers.id"),
            nullable=True,
        ),
        # Inline so SQLite auto-migrate can emit the CHECK; a
        # post-create op.create_check_constraint() raises
        # NotImplementedError on SQLite.
        sa.CheckConstraint(
            "category IN ('source', 'deploy', 'runtime', 'contract', 'operator')",
            name="ck_blockers_category_values",
        ),
    )
    # Single composite partial covers every open-blocker access
    # pattern Phase II + VI care about: per-task "any open blocker?",
    # board-wide "list open blockers", and the is_blocked batch
    # preload. board_id is always known at query time because every
    # endpoint is nested under /boards/{board_id}.
    op.create_index(
        "ix_blockers_board_id_task_id_open",
        "blockers",
        ["board_id", "task_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )
    # Race-proofs concurrent supersede: two POSTs both citing the same
    # supersedes_blocker_id would otherwise each pass the
    # prior.resolved_at IS NULL check and both insert a sharpening,
    # leaving the prior row ambiguous. The partial unique index makes
    # the second inserter fail at the DB layer.
    op.create_index(
        "uq_blockers_supersedes_blocker_id_open",
        "blockers",
        ["supersedes_blocker_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_blocker_id IS NOT NULL"),
        sqlite_where=sa.text("supersedes_blocker_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_blockers_supersedes_blocker_id_open", table_name="blockers")
    op.drop_index("ix_blockers_board_id_task_id_open", table_name="blockers")
    op.drop_table("blockers")
