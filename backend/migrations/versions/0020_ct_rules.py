"""Circuits: rules per type (moved, missing and VLAN checks and emails).

Revision ID: 0020_ct_rules
Revises: 0019_ct_carriers
Created: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_ct_rules"
down_revision = "0019_ct_carriers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("email_moved", sa.Boolean(), nullable=False),
        sa.Column("email_missing", sa.Boolean(), nullable=False),
        sa.Column("missing_hours", sa.Integer(), nullable=False),
        sa.Column("check_vlan", sa.Boolean(), nullable=False),
        sa.Column("vlans", sa.String(length=255), nullable=False),
        sa.Column("email_vlan", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ct_rules")
