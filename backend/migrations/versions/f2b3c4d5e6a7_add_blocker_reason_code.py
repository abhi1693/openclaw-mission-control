"""add reason_code to blockers and operator_decisions

Plan §I1/§I3 hardening: structured fine-grained reason code that
complements ``Blocker.category`` (5-value coarse bucket) and
``OperatorDecision.unblock_rule`` (free-text). Open vocabulary, no CHECK
constraint — readers must treat unknown codes as opaque. Recommended
starter codes: ``gateway_ws_timeout``, ``deploy_drift``,
``operator_policy``, ``credential_required``, ``external_dependency``,
``requirements_clarification``, ``infra_other``.

Additive, nullable, no backfill. Existing rows keep ``reason_code = NULL``
and behave identically to the pre-migration shape.

Revision ID: f2b3c4d5e6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-30 19:30:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "f2b3c4d5e6a7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blockers",
        sa.Column("reason_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "operator_decisions",
        sa.Column("reason_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    # Mirror upgrade order for symmetry; both columns are independent so
    # the order doesn't affect correctness.
    op.drop_column("blockers", "reason_code")
    op.drop_column("operator_decisions", "reason_code")
