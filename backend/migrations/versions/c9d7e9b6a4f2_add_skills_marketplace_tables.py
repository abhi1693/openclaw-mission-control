"""add skills marketplace tables

Revision ID: c9d7e9b6a4f2
Revises: b6f4c7d9e1a2
Create Date: 2026-02-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision = "c9d7e9b6a4f2"
down_revision = "b05c7b628636"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    if not _has_table(table_name):
        return False
    constraints = sa.inspect(op.get_bind()).get_check_constraints(table_name)
    return any(constraint["name"] == constraint_name for constraint in constraints)


def upgrade() -> None:
    if not _has_table("marketplace_skills"):
        op.create_table(
            "marketplace_skills",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("risk", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("source_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["organization_id"],
                ["organizations.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "source_url",
                name="uq_marketplace_skills_org_source_url",
            ),
        )
    if not _has_column("marketplace_skills", "metadata"):
        op.add_column(
            "marketplace_skills",
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    if _has_column("marketplace_skills", "resolution_metadata") and not _has_column(
        "marketplace_skills", "metadata",
    ):
        op.execute(
            sa.text(
                "UPDATE marketplace_skills SET metadata = resolution_metadata WHERE resolution_metadata IS NOT NULL"
            )
        )
    elif _has_column("marketplace_skills", "path_metadata") and not _has_column(
        "marketplace_skills", "metadata"
    ):
        op.execute(
            sa.text(
                "UPDATE marketplace_skills SET metadata = path_metadata WHERE path_metadata IS NOT NULL"
            )
        )

    marketplace_org_idx = op.f("ix_marketplace_skills_organization_id")
    if not _has_index("marketplace_skills", marketplace_org_idx):
        op.create_index(
            marketplace_org_idx,
            "marketplace_skills",
            ["organization_id"],
            unique=False,
        )

    if not _has_table("gateway_installed_skills"):
        op.create_table(
            "gateway_installed_skills",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("gateway_id", sa.Uuid(), nullable=False),
            sa.Column("skill_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["gateway_id"],
                ["gateways.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["skill_id"],
                ["marketplace_skills.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "gateway_id",
                "skill_id",
                name="uq_gateway_installed_skills_gateway_id_skill_id",
            ),
        )

    gateway_id_idx = op.f("ix_gateway_installed_skills_gateway_id")
    if not _has_index("gateway_installed_skills", gateway_id_idx):
        op.create_index(
            gateway_id_idx,
            "gateway_installed_skills",
            ["gateway_id"],
            unique=False,
        )

    gateway_skill_idx = op.f("ix_gateway_installed_skills_skill_id")
    if not _has_index("gateway_installed_skills", gateway_skill_idx):
        op.create_index(
            gateway_skill_idx,
            "gateway_installed_skills",
            ["skill_id"],
            unique=False,
        )

    if not _has_table("skill_packs"):
        op.create_table(
            "skill_packs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("source_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "branch",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default=sa.text("'main'"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["organization_id"],
                ["organizations.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "source_url",
                name="uq_skill_packs_org_source_url",
            ),
        )
    if not _has_constraint(
        "skill_packs",
        "ck_skill_packs_source_url_github",
    ):
        op.create_check_constraint(
            "ck_skill_packs_source_url_github",
            "skill_packs",
            "source_url LIKE 'https://github.com/%/%'",
        )
    if not _has_column("skill_packs", "branch"):
        op.add_column(
            "skill_packs",
            sa.Column(
                "branch",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default=sa.text("'main'"),
            ),
        )
    if not _has_column("skill_packs", "metadata"):
        op.add_column(
            "skill_packs",
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    if _has_column("skill_packs", "resolution_metadata") and not _has_column(
        "skill_packs", "metadata"
    ):
        op.execute(
            sa.text(
                "UPDATE skill_packs SET metadata = resolution_metadata WHERE resolution_metadata IS NOT NULL"
            )
        )
    elif _has_column("skill_packs", "path_metadata") and not _has_column(
        "skill_packs", "metadata"
    ):
        op.execute(
            sa.text(
                "UPDATE skill_packs SET metadata = path_metadata WHERE path_metadata IS NOT NULL"
            )
        )

    skill_packs_org_idx = op.f("ix_skill_packs_organization_id")
    if not _has_index("skill_packs", skill_packs_org_idx):
        op.create_index(
            skill_packs_org_idx,
            "skill_packs",
            ["organization_id"],
            unique=False,
        )


def downgrade() -> None:
    skill_pack_github_constraint = "ck_skill_packs_source_url_github"
    if _has_constraint("skill_packs", skill_pack_github_constraint):
        op.drop_constraint(
            skill_pack_github_constraint,
            "skill_packs",
            type_="check",
        )

    skill_packs_org_idx = op.f("ix_skill_packs_organization_id")
    if _has_index("skill_packs", skill_packs_org_idx):
        op.drop_index(
            skill_packs_org_idx,
            table_name="skill_packs",
        )

    if _has_table("skill_packs"):
        op.drop_table("skill_packs")

    gateway_skill_idx = op.f("ix_gateway_installed_skills_skill_id")
    if _has_index("gateway_installed_skills", gateway_skill_idx):
        op.drop_index(
            gateway_skill_idx,
            table_name="gateway_installed_skills",
        )

    gateway_id_idx = op.f("ix_gateway_installed_skills_gateway_id")
    if _has_index("gateway_installed_skills", gateway_id_idx):
        op.drop_index(
            gateway_id_idx,
            table_name="gateway_installed_skills",
        )

    if _has_table("gateway_installed_skills"):
        op.drop_table("gateway_installed_skills")

    marketplace_org_idx = op.f("ix_marketplace_skills_organization_id")
    if _has_index("marketplace_skills", marketplace_org_idx):
        op.drop_index(
            marketplace_org_idx,
            table_name="marketplace_skills",
        )

    if _has_table("marketplace_skills"):
        op.drop_table("marketplace_skills")
