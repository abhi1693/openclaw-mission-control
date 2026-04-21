"""phase II part 2: blocker.citation column + reviews task/created_at index

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-21 17:30:00.000000

Follow-up changes that emerged from the /simplify + /codex review gauntlet
on Phase II reviews + is_blocked work:

- ``blockers.citation`` — plan §I4 lists citation as a per-blocker
  field. The POST /reviews path threads ``ReviewBlockerDescriptor.citation``
  into the blocker row and the BlockerRead / ReviewBlockerRead schemas
  surface it on reads. POST /blockers also persists it; PATCH accepts
  it as one of the sharpenable fields.

- ``ix_reviews_task_id_created_at`` — ``list_task_reviews`` orders by
  ``created_at DESC`` under a ``task_id`` filter. A composite keeps
  the scan index-only for tasks with rework-cycle review history.

Lives in a separate revision (not an in-place edit of
``a1b2c3d4e5f6``/``b2c3d4e5f6a7``) so any environment that stamped the
original Phase II revisions picks up these additions on the next
``alembic upgrade head``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blockers",
        sa.Column("citation", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_reviews_task_id_created_at",
        "reviews",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_task_id_created_at", table_name="reviews")
    op.drop_column("blockers", "citation")
