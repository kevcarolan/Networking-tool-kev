"""Settings made in the GUI (first-run setup and the Settings page).

Revision ID: 0002_app_settings
Revises: 0001_baseline
Created: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_app_settings"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
