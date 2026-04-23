"""Part E.1: auth-status snapshot on heartbeat-repair rows.

Revision ID: d20eab11ad02
Revises: c10ab11ad01
Create Date: 2026-04-23

Adds a nullable JSON column on ``agent_heartbeat_repair_events`` that
captures the per-gateway ``models.authStatus`` snapshot at the moment
of each repair. Forensic-only for the first landing — operators can
correlate repair spikes with provider-side OAuth expiry / rate-limit
pressure without cross-referencing the gateway logs. A follow-up
commit gates the existing "3× repair / 1h" WARN on the snapshot.

Column is JSON (not JSONB) to match the Phase 0 ``shadow_metric_events``
pattern — SQLite-compatible for local tests, transparent for
Postgres. Snapshot is raw verbatim; the gateway's own cache + strip
contract (no credentials, 60s cache) is the truth source.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d20eab11ad02"
down_revision = "c10ab11ad01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_heartbeat_repair_events",
        sa.Column("auth_status_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_heartbeat_repair_events", "auth_status_snapshot")
