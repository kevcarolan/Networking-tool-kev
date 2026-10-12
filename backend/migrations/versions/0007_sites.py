"""The site list, and the columns an admin adds to it.

Revision ID: 0007_sites
Revises: 0006_circuit_columns
Created: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_sites"
down_revision = "0006_circuit_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("choices", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("postcode", sa.String(length=30), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("contact", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("access", sa.Text(), nullable=False),
        sa.Column("circuits", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("custom", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sites", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sites_name"), ["name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sites", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sites_name"))
    op.drop_table("sites")
    op.drop_table("site_fields")
