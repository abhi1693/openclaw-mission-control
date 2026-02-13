"""merge heads after board lead rule

Revision ID: d3ca36cf31a1
Revises: 1a7b2c3d4e5f, 836cf8009001
Create Date: 2026-02-13 11:02:04.893298

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3ca36cf31a1'
down_revision = ('1a7b2c3d4e5f', '836cf8009001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
