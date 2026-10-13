"""Wall displays: the pages each screen shows.

Revision ID: 0011_display_pages
Revises: 0010_compliance
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_display_pages"
down_revision = "0010_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("display_screens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pages", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("display_screens", schema=None) as batch_op:
        batch_op.drop_column("pages")
