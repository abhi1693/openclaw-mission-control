"""merge heads

Revision ID: bbd5bbb26d97
Revises: 99cd6df95f85, b4338be78eec
Create Date: 2026-02-12 09:54:21.149702

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bbd5bbb26d97'
down_revision = ('99cd6df95f85', 'b4338be78eec')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
