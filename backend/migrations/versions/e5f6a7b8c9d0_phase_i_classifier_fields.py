"""phase I: classifier_flags on activity_events + comment_signal_filter on boards

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-21 10:00:00.000000

Adds two denormalized/config columns that Phase I needs:

- ``activity_events.classifier_flags`` (JSON, nullable) — list of
  classifier flag strings stamped at write time by the shadow-metric
  emitter. Denormalized from shadow_metric_events so ``GET /comments``
  can filter without a join per read.

- ``boards.comment_signal_filter`` (String, not null, default 'off') —
  per-board filter mode controlling whether flagged comments are
  shown, hidden, or hidden-strictly from agent-token callers. Initial
  rollout value on all boards is 'off' (classifier flags populate but
  no UI behavior changes). Boards graduate to 'default_hidden' only
  after Phase II blocker objects ship + the classifier FPR gate
  passes, per amendments §1.

See docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md
sections 4.1 and 4.3.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activity_events",
        sa.Column("classifier_flags", sa.JSON(), nullable=True),
    )
    op.add_column(
        "boards",
        sa.Column(
            "comment_signal_filter",
            sa.String(length=32),
            nullable=False,
            server_default="off",
        ),
    )
    # Clear the server default after backfill so the model stays the
    # single source of truth for new rows — same pattern as the
    # rollout_flags migration (b2c3d4e5f6a7).
    op.alter_column("boards", "comment_signal_filter", server_default=None)
    # Defense-in-depth: the Pydantic Literal validates API writes, but
    # raw SQL, data fixtures, and external tools bypass that layer.
    # A CHECK constraint makes the 3-value enum DB-enforced.
    op.create_check_constraint(
        "ck_boards_comment_signal_filter_values",
        "boards",
        "comment_signal_filter IN ('off', 'default_hidden', 'hidden_strict')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_boards_comment_signal_filter_values",
        "boards",
        type_="check",
    )
    op.drop_column("boards", "comment_signal_filter")
    op.drop_column("activity_events", "classifier_flags")
