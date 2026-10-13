"""Topology map: each device's neighbours at the last scan, and boxes people moved.

Revision ID: 0012_topology
Revises: 0011_display_pages
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_topology"
down_revision = "0011_display_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_live_neighbors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("local_port", sa.String(length=100), nullable=False),
        sa.Column("local_norm", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("remote_port", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=200), nullable=False),
        sa.Column("infra", sa.Boolean(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ct_live_neighbors", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ct_live_neighbors_device_id"), ["device_id"],
                              unique=False)
    op.create_table(
        "ct_topology_positions",
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=300), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("site_id", "node"),
    )


def downgrade() -> None:
    op.drop_table("ct_topology_positions")
    with op.batch_alter_table("ct_live_neighbors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ct_live_neighbors_device_id"))
    op.drop_table("ct_live_neighbors")
