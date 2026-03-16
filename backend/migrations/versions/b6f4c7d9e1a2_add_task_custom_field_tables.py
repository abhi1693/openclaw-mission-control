"""Add task custom field tables.

Revision ID: b6f4c7d9e1a2
Revises: 1a7b2c3d4e5f
Create Date: 2026-02-13 00:20:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b6f4c7d9e1a2"
down_revision = "1a7b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create task custom-field definition, binding, and value tables."""
    op.create_table(
        "task_custom_field_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "field_type",
            sa.String(),
            nullable=False,
            server_default=sa.text("'text'"),
        ),
        sa.Column(
            "ui_visibility",
            sa.String(),
            nullable=False,
            server_default=sa.text("'always'"),
        ),
        sa.Column("validation_regex", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("default_value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "field_key",
            name="uq_tcf_def_org_key",
        ),
        sa.CheckConstraint(
            "field_type IN "
            "('text','text_long','integer','decimal','boolean','date','date_time','url','json')",
            name="ck_tcf_def_field_type",
        ),
        sa.CheckConstraint(
            "ui_visibility IN ('always','if_set','hidden')",
            name="ck_tcf_def_ui_visibility",
        ),
    )
    op.create_index(
        "ix_task_custom_field_definitions_organization_id",
        "task_custom_field_definitions",
        ["organization_id"],
    )
    op.create_index(
        "ix_task_custom_field_definitions_field_key",
        "task_custom_field_definitions",
        ["field_key"],
    )

    op.create_table(
        "board_task_custom_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("task_custom_field_definition_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(
            ["task_custom_field_definition_id"],
            ["task_custom_field_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "board_id",
            "task_custom_field_definition_id",
            name="uq_board_tcf_binding",
        ),
    )
    op.create_index(
        "ix_board_task_custom_fields_board_id",
        "board_task_custom_fields",
        ["board_id"],
    )
    op.create_index(
        "ix_board_task_custom_fields_task_custom_field_definition_id",
        "board_task_custom_fields",
        ["task_custom_field_definition_id"],
    )

    op.create_table(
        "task_custom_field_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_custom_field_definition_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(
            ["task_custom_field_definition_id"],
            ["task_custom_field_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "task_custom_field_definition_id",
            name="uq_tcf_values_task_def",
        ),
    )
    op.create_index(
        "ix_task_custom_field_values_task_id",
        "task_custom_field_values",
        ["task_id"],
    )
    op.create_index(
        "ix_task_custom_field_values_task_custom_field_definition_id",
        "task_custom_field_values",
        ["task_custom_field_definition_id"],
    )


def downgrade() -> None:
    """Drop task custom field tables."""
    op.drop_table("task_custom_field_values")
    op.drop_table("board_task_custom_fields")
    op.drop_table("task_custom_field_definitions")
