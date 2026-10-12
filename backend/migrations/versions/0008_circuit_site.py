"""Circuit list: a Site column (a site's name or code).

Revision ID: 0008_circuit_site
Revises: 0007_sites
Created: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_circuit_site"
down_revision = "0007_sites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ct_circuits", schema=None) as batch_op:
        batch_op.add_column(sa.Column("site", sa.String(length=100), server_default="",
                                      nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("ct_circuits", schema=None) as batch_op:
        batch_op.drop_column("site")
