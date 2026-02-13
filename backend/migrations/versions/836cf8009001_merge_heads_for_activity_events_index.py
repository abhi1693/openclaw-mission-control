"""merge heads for activity_events index

Revision ID: 836cf8009001
Revises: b05c7b628636, fa6e83f8d9a1
Create Date: 2026-02-13 10:57:21.395382

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '836cf8009001'
down_revision = ('b05c7b628636', 'fa6e83f8d9a1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
