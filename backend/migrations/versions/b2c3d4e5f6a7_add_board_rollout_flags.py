"""add board rollout_flags and rollout_flags_unknown

Revision ID: b2c3d4e5f6a7
Revises: e4b7c1d2a9f8
Create Date: 2026-04-17 13:30:00.000000

Adds two JSON columns on ``boards`` for phased invariant rollout:

- ``rollout_flags`` -- boolean feature-flag map, allowlisted keys only.
- ``rollout_flags_unknown`` -- capture bucket for keys not in the allowlist.
  Accepted at the API layer but not acted on. Observable so operators can
  see which future-phase flags are being attempted before the allowlist
  adds them.

See ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
sections A.3 and A.7 for rationale.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "e4b7c1d2a9f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default='{}' works on both PostgreSQL JSON and SQLite JSON
    # storage. App-layer default_factory keeps the same value for rows
    # created via the ORM.
    op.add_column(
        "boards",
        sa.Column(
            "rollout_flags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "boards",
        sa.Column(
            "rollout_flags_unknown",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    # Clear server defaults after backfill so the model is the single
    # source of truth for new rows going forward.
    op.alter_column("boards", "rollout_flags", server_default=None)
    op.alter_column("boards", "rollout_flags_unknown", server_default=None)


def downgrade() -> None:
    op.drop_column("boards", "rollout_flags_unknown")
    op.drop_column("boards", "rollout_flags")
