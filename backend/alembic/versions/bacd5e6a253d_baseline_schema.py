"""baseline schema (no HR module)

Revision ID: bacd5e6a253d
Revises:
Create Date: 2026-02-02 16:37:34.122971

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bacd5e6a253d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Departments (FK to employees added after employees table exists)
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("head_employee_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_departments_name"), "departments", ["name"], unique=True)

    # Employees
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("employee_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("openclaw_session_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("notify_enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["manager_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Break the departments<->employees cycle: add this FK after both tables exist
    op.create_foreign_key(None, "departments", "employees", ["head_employee_id"], ["id"])

    # Projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=True)

    # Activities
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_employee_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("verb", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Project members
    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("assignee_employee_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assignee_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["created_by_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewer_employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)

    # Task comments
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("author_employee_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_comment_id", sa.Integer(), nullable=True),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["reply_to_comment_id"], ["task_comments.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_comments_task_id"), "task_comments", ["task_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(op.f("ix_task_comments_task_id"), table_name="task_comments")
    op.drop_table("task_comments")

    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_table("tasks")

    op.drop_table("project_members")

    op.drop_table("activities")

    op.drop_index(op.f("ix_projects_name"), table_name="projects")
    op.drop_table("projects")

    op.drop_table("employees")

    op.drop_index(op.f("ix_departments_name"), table_name="departments")
    op.drop_table("departments")
