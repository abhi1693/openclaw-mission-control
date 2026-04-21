"""phase II: structured blocker sidecar table

Revision ID: a1b2c3d4e5f6
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


revision = "a1b2c3d4e5f6"
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
    # Fast "does this task have any open blocker?" lookup powers the
    # is_blocked derivation that lands in a follow-up commit.
    op.create_index(
        "ix_blockers_task_id_open",
        "blockers",
        ["task_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )
    # Phase VI lane-quieting + the Supervisor dashboard both scan for
    # open blockers at board scope. Partial keeps the index tiny vs.
    # the full board_id index that would cover every historical row.
    op.create_index(
        "ix_blockers_board_id_open",
        "blockers",
        ["board_id"],
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
    op.drop_index("ix_blockers_board_id_open", table_name="blockers")
    op.drop_index("ix_blockers_task_id_open", table_name="blockers")
    op.drop_table("blockers")
