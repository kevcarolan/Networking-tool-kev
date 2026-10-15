"""Monitoring: custom SNMP sensors.

Revision ID: 0017_sensors
Revises: 0016_meraki
Created: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_sensors"
down_revision = "0016_meraki"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mon_sensors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("oid", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("table", sa.Boolean(), nullable=False),
        sa.Column("label_oid", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("scale", sa.Float(), nullable=False),
        sa.Column("warn_above", sa.Float(), nullable=True),
        sa.Column("crit_above", sa.Float(), nullable=True),
        sa.Column("warn_below", sa.Float(), nullable=True),
        sa.Column("crit_below", sa.Float(), nullable=True),
        sa.Column("ok_values", sa.String(length=100), nullable=False),
        sa.Column("warn_values", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("device_ids", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("mon_sensors")
