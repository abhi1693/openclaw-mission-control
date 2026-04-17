"""add shadow_metric_events table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-17 15:30:00.000000

Append-only observability table for Phase 0 shadow classifiers and
gate instrumentation. Each row captures a signal (ack-only candidate,
near-duplicate candidate, actionability violation) without changing
caller-visible behavior.

See ``docs/plans/2026-04-16-mc-delivery-enforcement-plan.md`` §Phase 0
and amendments §A.2, §A.4, §A.5.

Retention: 90-day cutoff via downstream purge job (amendment §A.4).
The ``created_at`` index makes that purge query efficient without
needing a dedicated time-range scan plan.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No new activity_events index needed: 99cd6df95f85 already ships a
    # partial index ix_activity_events_task_comment_task_id_created_at
    # on (task_id, created_at) WHERE event_type='task.comment' that
    # serves the classifier's prior-lookup. PG filters the per-task
    # result on agent_id after the range scan — selective enough at
    # Dev-Squad scale.
    op.create_table(
        "shadow_metric_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("boards.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("classifier_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        op.f("ix_shadow_metric_events_event_type"),
        "shadow_metric_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shadow_metric_events_created_at"),
        "shadow_metric_events",
        ["created_at"],
        unique=False,
    )
    # Composite for "prior comment by same author on same task within window"
    # lookups from the classifier emitter — see services/shadow_metrics.py.
    # Also usable for operator queries filtering a task's metric history.
    op.create_index(
        op.f("ix_shadow_metric_events_task_agent_created"),
        "shadow_metric_events",
        ["task_id", "agent_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shadow_metric_events_task_agent_created"),
        table_name="shadow_metric_events",
    )
    op.drop_index(
        op.f("ix_shadow_metric_events_created_at"),
        table_name="shadow_metric_events",
    )
    op.drop_index(
        op.f("ix_shadow_metric_events_event_type"),
        table_name="shadow_metric_events",
    )
    op.drop_table("shadow_metric_events")
