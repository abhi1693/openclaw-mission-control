"""Part E.4: promote PAIRING_REQUIRED request_id into structured Blocker field.

Revision ID: d30eab11ad03
Revises: d20eab11ad02
Create Date: 2026-04-23

4.20 `#69227` added reason-specific remediation hints + ``request_id``
to ``PAIRING_REQUIRED`` responses. D.2's ``_citation_for`` preserves
the request_id inside the free-form citation, but the 512-char cap
risks clipping it on long remediation messages. Operators need the
id to cross-reference gateway logs when triaging a stuck agent.

Adds a nullable ``citation_request_id`` column so the id is
searchable / sortable independently of citation text. Citation text
itself keeps the id for human readability — this is an addition, not
a migration away.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d30eab11ad03"
down_revision = "d20eab11ad02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blockers",
        sa.Column("citation_request_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blockers", "citation_request_id")
