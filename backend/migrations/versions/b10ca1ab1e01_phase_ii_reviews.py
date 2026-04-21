"""phase II: reviews + review_blockers sidecar tables

Revision ID: b10ca1ab1e01
Revises: b10ca1ab1e00
Create Date: 2026-04-21 16:30:00.000000

Adds the two tables that back Phase II §I4 "reviews emit structured
blockers, not prose":

- ``reviews`` — one row per verdict the reviewer submitted.
- ``review_blockers`` — join table linking a Review to the Blocker
  rows it cited. Unique per (review_id, blocker_id) so a review can't
  double-count the same blocker.

See docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I4.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b10ca1ab1e01"
down_revision = "b10ca1ab1e00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # board_id carries tenant scope; no board-wide reviews index
        # is added because the access pattern is task-scoped.
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("boards.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("citation", sa.Text(), nullable=True),
        sa.Column(
            "reviewer_agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Inline CHECK — op.create_check_constraint() after a
        # create_table() raises NotImplementedError on SQLite and the
        # dev auto-migrator runs against SQLite.
        sa.CheckConstraint(
            "verdict IN ('pass', 'fail', 'needs_changes')",
            name="ck_reviews_verdict_values",
        ),
    )
    op.create_table(
        "review_blockers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # Unique (review_id, blocker_id) below already indexes
        # review_id as the prefix column — no separate review_id index.
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("reviews.id"),
            nullable=False,
        ),
        sa.Column(
            "blocker_id",
            sa.Uuid(),
            sa.ForeignKey("blockers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "review_id",
            "blocker_id",
            name="uq_review_blockers_review_id_blocker_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_blockers")
    op.drop_table("reviews")
