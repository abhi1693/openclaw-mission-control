"""Allow duplicate organization names.

Revision ID: a1e6b0d62f0c
Revises: 658dca8f4a11
Create Date: 2026-02-09 00:00:00.000000

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1e6b0d62f0c"
down_revision = "658dca8f4a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop global unique constraint on organization names."""
    op.drop_constraint("uq_organizations_name", "organizations", type_="unique")


def downgrade() -> None:
    """Restore global unique constraint on organization names."""
    op.create_unique_constraint(
        "uq_organizations_name",
        "organizations",
        ["name"],
    )
