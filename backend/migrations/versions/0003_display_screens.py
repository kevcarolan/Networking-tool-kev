"""Wall displays allowed to read the status dashboard.

Revision ID: 0003_display_screens
Revises: 0002_app_settings
Created: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_display_screens"
down_revision = "0002_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "display_screens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_from", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )


def downgrade() -> None:
    op.drop_table("display_screens")
