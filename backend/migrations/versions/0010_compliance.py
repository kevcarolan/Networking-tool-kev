"""Config compliance: rules, and each device's latest result per rule.

Revision ID: 0010_compliance
Revises: 0009_site_layout
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_compliance"
down_revision = "0009_site_layout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("lines", sa.Text(), nullable=False),
        sa.Column("regex", sa.Boolean(), nullable=False),
        sa.Column("platforms", sa.Text(), nullable=False),
        sa.Column("sites", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "compliance_results",
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("failing_since", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["compliance_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "rule_id"),
    )


def downgrade() -> None:
    op.drop_table("compliance_results")
    op.drop_table("compliance_rules")
