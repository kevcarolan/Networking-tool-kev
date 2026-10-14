"""Monitoring: SNMP profiles and each device's monitoring choices.

Revision ID: 0015_monitoring
Revises: 0014_calendar
Created: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_monitoring"
down_revision = "0014_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mon_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=5), nullable=False),
        sa.Column("community_enc", sa.Text(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("auth_protocol", sa.String(length=10), nullable=False),
        sa.Column("auth_key_enc", sa.Text(), nullable=False),
        sa.Column("priv_protocol", sa.String(length=10), nullable=False),
        sa.Column("priv_key_enc", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "mon_targets",
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("ping", sa.Boolean(), nullable=False),
        sa.Column("snmp", sa.Boolean(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["mon_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("device_id"),
    )


def downgrade() -> None:
    op.drop_table("mon_targets")
    op.drop_table("mon_profiles")
