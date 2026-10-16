"""Circuits: saved spreadsheet layouts (column mappings).

Revision ID: 0018_ct_column_maps
Revises: 0017_sensors
Created: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_ct_column_maps"
down_revision = "0017_sensors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_column_maps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("headers", sa.Text(), nullable=False),
        sa.Column("columns", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signature"),
    )


def downgrade() -> None:
    op.drop_table("ct_column_maps")
