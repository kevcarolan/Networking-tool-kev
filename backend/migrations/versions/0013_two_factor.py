"""Two-factor sign-in: each user's (encrypted) authenticator secret and recovery codes.

Revision ID: 0013_two_factor
Revises: 0012_topology
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_two_factor"
down_revision = "0012_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("totp_secret", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("totp_enabled", sa.Boolean(), server_default=sa.false(),
                                      nullable=False))
        batch_op.add_column(sa.Column("totp_last_step", sa.Integer(), server_default="0",
                                      nullable=False))
        batch_op.add_column(sa.Column("totp_enabled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("recovery_codes", sa.Text(), server_default="[]",
                                      nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("recovery_codes")
        batch_op.drop_column("totp_enabled_at")
        batch_op.drop_column("totp_last_step")
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")
