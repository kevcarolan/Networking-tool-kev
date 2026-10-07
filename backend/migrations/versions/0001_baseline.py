"""Baseline: the database as created before migrations were introduced (October 2026).

Existing installs are marked as being at this revision; new installs are created from the
models and marked as being at the latest one. So this migration changes nothing.

Revision ID: 0001_baseline
Revises:
Created: 2026-10-07
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
