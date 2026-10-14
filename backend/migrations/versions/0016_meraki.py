"""Meraki: organisations read through the Dashboard API.

Revision ID: 0016_meraki
Revises: 0015_monitoring
Created: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_meraki"
down_revision = "0015_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mon_meraki",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=200), nullable=False),
        sa.Column("org_id", sa.String(length=50), nullable=False),
        sa.Column("org_name", sa.String(length=200), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("mon_meraki")
