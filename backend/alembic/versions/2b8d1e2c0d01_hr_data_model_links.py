"""hr data model links (onboarding.employee_id, headcount fulfillment, employment action idempotency)

Revision ID: 2b8d1e2c0d01
Revises: 9d3d9b9c1a23
Create Date: 2026-02-02 09:05:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "2b8d1e2c0d01"
down_revision = "9d3d9b9c1a23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # headcount_requests fulfillment fields
    op.add_column("headcount_requests", sa.Column("fulfilled_employee_id", sa.Integer(), nullable=True))
    op.add_column("headcount_requests", sa.Column("fulfilled_onboarding_id", sa.Integer(), nullable=True))
    op.add_column("headcount_requests", sa.Column("fulfilled_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_headcount_fulfilled_employee", "headcount_requests", "employees", ["fulfilled_employee_id"], ["id"])
    op.create_foreign_key("fk_headcount_fulfilled_onboarding", "headcount_requests", "agent_onboardings", ["fulfilled_onboarding_id"], ["id"])

    # employment_actions idempotency key
    op.add_column("employment_actions", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_unique_constraint("uq_employment_actions_idempotency_key", "employment_actions", ["idempotency_key"])
    op.create_index("ix_employment_actions_idempotency_key", "employment_actions", ["idempotency_key"])

    # agent_onboardings employee link
    op.add_column("agent_onboardings", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_agent_onboardings_employee", "agent_onboardings", "employees", ["employee_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_agent_onboardings_employee", "agent_onboardings", type_="foreignkey")
    op.drop_column("agent_onboardings", "employee_id")

    op.drop_index("ix_employment_actions_idempotency_key", table_name="employment_actions")
    op.drop_constraint("uq_employment_actions_idempotency_key", "employment_actions", type_="unique")
    op.drop_column("employment_actions", "idempotency_key")

    op.drop_constraint("fk_headcount_fulfilled_onboarding", "headcount_requests", type_="foreignkey")
    op.drop_constraint("fk_headcount_fulfilled_employee", "headcount_requests", type_="foreignkey")
    op.drop_column("headcount_requests", "fulfilled_at")
    op.drop_column("headcount_requests", "fulfilled_onboarding_id")
    op.drop_column("headcount_requests", "fulfilled_employee_id")
