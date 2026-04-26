"""add workflow tables

Revision ID: d1f4e7a9b2c3
Revises: a9b1c2d3e4f7
Create Date: 2026-04-25 16:10:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1f4e7a9b2c3"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("trigger_mode", sa.String(), nullable=False, server_default="manual"),
        sa.Column("step_graph_json", sa.JSON(), nullable=True),
        sa.Column("default_policy_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_definitions_board_id"), "workflow_definitions", ["board_id"], unique=False)
    op.create_index(op.f("ix_workflow_definitions_organization_id"), "workflow_definitions", ["organization_id"], unique=False)
    op.create_index(op.f("ix_workflow_definitions_slug"), "workflow_definitions", ["slug"], unique=False)
    op.create_index(op.f("ix_workflow_definitions_status"), "workflow_definitions", ["status"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_definition_id", sa.Uuid(), nullable=True),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("current_step_key", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_agent_id", sa.Uuid(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_runs_board_id"), "workflow_runs", ["board_id"], unique=False)
    op.create_index(op.f("ix_workflow_runs_created_by_agent_id"), "workflow_runs", ["created_by_agent_id"], unique=False)
    op.create_index(op.f("ix_workflow_runs_created_by_user_id"), "workflow_runs", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_workflow_runs_current_step_key"), "workflow_runs", ["current_step_key"], unique=False)
    op.create_index(op.f("ix_workflow_runs_source_task_id"), "workflow_runs", ["source_task_id"], unique=False)
    op.create_index(op.f("ix_workflow_runs_status"), "workflow_runs", ["status"], unique=False)
    op.create_index(op.f("ix_workflow_runs_workflow_definition_id"), "workflow_runs", ["workflow_definition_id"], unique=False)

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("step_type", sa.String(), nullable=False, server_default="agent_task"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_agent_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("depends_on_step_ids_json", sa.JSON(), nullable=True),
        sa.Column("instructions", sa.String(), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_steps_approval_id"), "workflow_steps", ["approval_id"], unique=False)
    op.create_index(op.f("ix_workflow_steps_assigned_agent_id"), "workflow_steps", ["assigned_agent_id"], unique=False)
    op.create_index(op.f("ix_workflow_steps_assigned_user_id"), "workflow_steps", ["assigned_user_id"], unique=False)
    op.create_index(op.f("ix_workflow_steps_status"), "workflow_steps", ["status"], unique=False)
    op.create_index(op.f("ix_workflow_steps_step_key"), "workflow_steps", ["step_key"], unique=False)
    op.create_index(op.f("ix_workflow_steps_step_type"), "workflow_steps", ["step_type"], unique=False)
    op.create_index(op.f("ix_workflow_steps_task_id"), "workflow_steps", ["task_id"], unique=False)
    op.create_index(op.f("ix_workflow_steps_workflow_run_id"), "workflow_steps", ["workflow_run_id"], unique=False)

    op.create_table(
        "workflow_step_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_step_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_agent_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["workflow_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_step_events_actor_agent_id"), "workflow_step_events", ["actor_agent_id"], unique=False)
    op.create_index(op.f("ix_workflow_step_events_actor_user_id"), "workflow_step_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_workflow_step_events_event_type"), "workflow_step_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_workflow_step_events_workflow_run_id"), "workflow_step_events", ["workflow_run_id"], unique=False)
    op.create_index(op.f("ix_workflow_step_events_workflow_step_id"), "workflow_step_events", ["workflow_step_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_step_events_workflow_step_id"), table_name="workflow_step_events")
    op.drop_index(op.f("ix_workflow_step_events_workflow_run_id"), table_name="workflow_step_events")
    op.drop_index(op.f("ix_workflow_step_events_event_type"), table_name="workflow_step_events")
    op.drop_index(op.f("ix_workflow_step_events_actor_user_id"), table_name="workflow_step_events")
    op.drop_index(op.f("ix_workflow_step_events_actor_agent_id"), table_name="workflow_step_events")
    op.drop_table("workflow_step_events")

    op.drop_index(op.f("ix_workflow_steps_workflow_run_id"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_task_id"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_step_type"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_step_key"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_status"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_assigned_user_id"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_assigned_agent_id"), table_name="workflow_steps")
    op.drop_index(op.f("ix_workflow_steps_approval_id"), table_name="workflow_steps")
    op.drop_table("workflow_steps")

    op.drop_index(op.f("ix_workflow_runs_workflow_definition_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_status"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_source_task_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_current_step_key"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_created_by_user_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_created_by_agent_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_board_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index(op.f("ix_workflow_definitions_status"), table_name="workflow_definitions")
    op.drop_index(op.f("ix_workflow_definitions_slug"), table_name="workflow_definitions")
    op.drop_index(op.f("ix_workflow_definitions_organization_id"), table_name="workflow_definitions")
    op.drop_index(op.f("ix_workflow_definitions_board_id"), table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
