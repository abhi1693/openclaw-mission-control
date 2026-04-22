"""Part D feeder-dedupe partial unique indexes.

Revision ID: c10ab11ad01
Revises: b10ca1ab1e05
Create Date: 2026-04-22

D.1 (subagent_failure_blocker) and D.2 (stale_agent_blocker) both
check-then-insert for dedupe — two concurrent ingest events for the
same (task, category-specific dedupe key) can race past the EXISTS
check and produce duplicate open blockers. The feeders note this as
a documented single-worker constraint.

This migration closes that race at the DB layer with a partial unique
index per feeder, so the second racer's INSERT fails with
IntegrityError and the caller rolls back cleanly. Both indexes are
partial on ``resolved_at IS NULL`` so the constraint only governs
open rows — once the operator resolves a blocker, a recurrence can
file fresh.

Dedupe key per category:

- ``runtime`` (D.1): ``(board_id, task_id, owner_role)`` — the parent
  task plus the child-agent role that failed. ``owner_role`` is
  always non-null because the parser rejects payloads without
  ``requested_role``.
- ``operator`` (D.2): ``(board_id, task_id, required_artifact)`` —
  the stale-agent artifact text is the operator-facing routing key.
  The index additionally filters ``required_artifact IS NOT NULL``
  so ad-hoc operator blockers filed without an artifact (reviewer
  judgment calls) are not constrained.

These indexes do not affect filings through ``POST /blockers`` when
the artifact/owner pair is distinct per call; they only fire on
storm-retry paths that would otherwise stamp duplicate rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c10ab11ad01"
down_revision = "b10ca1ab1e05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_blockers_runtime_owner_open",
        "blockers",
        ["board_id", "task_id", "owner_role"],
        unique=True,
        postgresql_where=sa.text(
            "category = 'runtime' AND resolved_at IS NULL"
        ),
        sqlite_where=sa.text(
            "category = 'runtime' AND resolved_at IS NULL"
        ),
    )
    op.create_index(
        "uq_blockers_operator_artifact_open",
        "blockers",
        ["board_id", "task_id", "required_artifact"],
        unique=True,
        postgresql_where=sa.text(
            "category = 'operator' "
            "AND resolved_at IS NULL "
            "AND required_artifact IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "category = 'operator' "
            "AND resolved_at IS NULL "
            "AND required_artifact IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_blockers_operator_artifact_open", table_name="blockers")
    op.drop_index("uq_blockers_runtime_owner_open", table_name="blockers")
