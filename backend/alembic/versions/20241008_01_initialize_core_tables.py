"""initialize core tables

Revision ID: 20241008_01
Revises:
Create Date: 2025-10-09 03:09:25.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20241008_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    membership_role_enum = sa.Enum(
        "owner",
        "admin",
        "member",
        "viewer",
        name="membership_role",
    )
    op.create_table(
        "user",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)

    op.create_table(
        "organization",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "membership",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", membership_role_enum, nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
    )

    op.create_table(
        "auditlog",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("actor_user_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("target", sa.String(length=255)),
        sa.Column("context", sa.JSON()),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"]),
    )


def downgrade() -> None:
    op.drop_table("auditlog")
    op.drop_table("membership")
    op.drop_table("organization")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
    membership_role_enum = sa.Enum(
        "owner",
        "admin",
        "member",
        "viewer",
        name="membership_role",
    )
    membership_role_enum.drop(op.get_bind(), checkfirst=True)
