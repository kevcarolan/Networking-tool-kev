"""Maintenance calendar: changes, maintenance, outages and change freezes.

Revision ID: 0012_calendar
Revises: 0011_display_pages
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_calendar"
down_revision = "0011_display_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cal_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("end", sa.DateTime(), nullable=False),
        sa.Column("sites", sa.Text(), nullable=False),
        sa.Column("devices", sa.Text(), nullable=False),
        sa.Column("change_ref", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("cal_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_cal_events_start"), ["start"], unique=False)
        batch_op.create_index(batch_op.f("ix_cal_events_end"), ["end"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cal_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_cal_events_end"))
        batch_op.drop_index(batch_op.f("ix_cal_events_start"))
    op.drop_table("cal_events")
