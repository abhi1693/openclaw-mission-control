"""Add board webhook configuration and payload storage tables.

Revision ID: fa6e83f8d9a1
Revises: c2e9f1a6d4b8
Create Date: 2026-02-13 00:10:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "fa6e83f8d9a1"
down_revision = "c2e9f1a6d4b8"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Create board webhook and payload capture tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("board_webhooks"):
        op.create_table(
            "board_webhooks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("board_id", sa.Uuid(), nullable=False),
            sa.Column("description", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    webhook_indexes = _index_names(inspector, "board_webhooks")
    if "ix_board_webhooks_board_id" not in webhook_indexes:
        op.create_index("ix_board_webhooks_board_id", "board_webhooks", ["board_id"])
    if "ix_board_webhooks_enabled" not in webhook_indexes:
        op.create_index("ix_board_webhooks_enabled", "board_webhooks", ["enabled"])

    if not inspector.has_table("board_webhook_payloads"):
        op.create_table(
            "board_webhook_payloads",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("board_id", sa.Uuid(), nullable=False),
            sa.Column("webhook_id", sa.Uuid(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("headers", sa.JSON(), nullable=True),
            sa.Column("source_ip", sa.String(), nullable=True),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
            sa.ForeignKeyConstraint(["webhook_id"], ["board_webhooks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    payload_indexes = _index_names(inspector, "board_webhook_payloads")
    if "ix_board_webhook_payloads_board_id" not in payload_indexes:
        op.create_index(
            "ix_board_webhook_payloads_board_id",
            "board_webhook_payloads",
            ["board_id"],
        )
    if "ix_board_webhook_payloads_webhook_id" not in payload_indexes:
        op.create_index(
            "ix_board_webhook_payloads_webhook_id",
            "board_webhook_payloads",
            ["webhook_id"],
        )
    if "ix_board_webhook_payloads_received_at" not in payload_indexes:
        op.create_index(
            "ix_board_webhook_payloads_received_at",
            "board_webhook_payloads",
            ["received_at"],
        )
    if "ix_board_webhook_payloads_board_webhook_received_at" not in payload_indexes:
        op.create_index(
            "ix_board_webhook_payloads_board_webhook_received_at",
            "board_webhook_payloads",
            ["board_id", "webhook_id", "received_at"],
        )


def downgrade() -> None:
    """Drop board webhook and payload capture tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("board_webhook_payloads"):
        payload_indexes = _index_names(inspector, "board_webhook_payloads")
        if "ix_board_webhook_payloads_board_webhook_received_at" in payload_indexes:
            op.drop_index(
                "ix_board_webhook_payloads_board_webhook_received_at",
                table_name="board_webhook_payloads",
            )
        if "ix_board_webhook_payloads_received_at" in payload_indexes:
            op.drop_index(
                "ix_board_webhook_payloads_received_at",
                table_name="board_webhook_payloads",
            )
        if "ix_board_webhook_payloads_webhook_id" in payload_indexes:
            op.drop_index(
                "ix_board_webhook_payloads_webhook_id",
                table_name="board_webhook_payloads",
            )
        if "ix_board_webhook_payloads_board_id" in payload_indexes:
            op.drop_index(
                "ix_board_webhook_payloads_board_id",
                table_name="board_webhook_payloads",
            )
        op.drop_table("board_webhook_payloads")

    inspector = sa.inspect(bind)
    if inspector.has_table("board_webhooks"):
        webhook_indexes = _index_names(inspector, "board_webhooks")
        if "ix_board_webhooks_enabled" in webhook_indexes:
            op.drop_index("ix_board_webhooks_enabled", table_name="board_webhooks")
        if "ix_board_webhooks_board_id" in webhook_indexes:
            op.drop_index("ix_board_webhooks_board_id", table_name="board_webhooks")
        op.drop_table("board_webhooks")
