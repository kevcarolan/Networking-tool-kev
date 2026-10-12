"""Email alerts that have been sent.

Revision ID: 0004_alerts_sent
Revises: 0003_display_screens
Created: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_alerts_sent"
down_revision = "0003_display_screens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts_sent",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("alerts_sent")
