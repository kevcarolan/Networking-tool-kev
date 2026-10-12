"""Network inventory: assets and the columns an admin adds.

Revision ID: 0005_inventory
Revises: 0004_alerts_sent
Created: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_inventory"
down_revision = "0004_alerts_sent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_fields",
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
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("manufacturer", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("serial", sa.String(length=100), nullable=False),
        sa.Column("asset_tag", sa.String(length=100), nullable=False),
        sa.Column("os", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("mgmt_ip", sa.String(length=255), nullable=False),
        sa.Column("mgmt_vlan", sa.String(length=20), nullable=False),
        sa.Column("mac", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("building", sa.String(length=100), nullable=False),
        sa.Column("floor", sa.String(length=50), nullable=False),
        sa.Column("room", sa.String(length=100), nullable=False),
        sa.Column("rack", sa.String(length=100), nullable=False),
        sa.Column("rack_position", sa.Integer(), nullable=True),
        sa.Column("rack_units", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("support_contract", sa.String(length=200), nullable=False),
        sa.Column("end_of_support", sa.Date(), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("custom", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assets_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_assets_serial"), ["serial"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assets_serial"))
        batch_op.drop_index(batch_op.f("ix_assets_name"))
    op.drop_table("assets")
    op.drop_table("asset_fields")
