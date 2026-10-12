"""Circuit list: the columns an admin adds, and their values on each row.

Revision ID: 0006_circuit_columns
Revises: 0005_inventory
Created: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_circuit_columns"
down_revision = "0005_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    with op.batch_alter_table("ct_circuits", schema=None) as batch_op:
        batch_op.add_column(sa.Column("custom", sa.Text(), server_default="{}", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("ct_circuits", schema=None) as batch_op:
        batch_op.drop_column("custom")
    op.drop_table("ct_fields")
