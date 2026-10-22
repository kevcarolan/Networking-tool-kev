"""Circuits: carrier circuits (provider lines).

Revision ID: 0019_ct_carriers
Revises: 0018_ct_column_maps
Created: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_ct_carriers"
down_revision = "0018_ct_column_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_carriers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=200), nullable=False),
        sa.Column("circuit_ref", sa.String(length=200), nullable=False),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("bandwidth", sa.String(length=100), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("interface", sa.String(length=100), nullable=False),
        sa.Column("wan_ip", sa.String(length=100), nullable=False),
        sa.Column("contract_end", sa.Date(), nullable=True),
        sa.Column("cost", sa.String(length=100), nullable=False),
        sa.Column("support", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ct_carriers")
