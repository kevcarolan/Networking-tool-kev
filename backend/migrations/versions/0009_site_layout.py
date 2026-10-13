"""Site layout: buildings, floors and rooms; a rack item's face and depth.

Revision ID: 0009_site_layout
Revises: 0008_circuit_site
Created: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_site_layout"
down_revision = "0008_circuit_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["site_locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("site_locations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_site_locations_site_id"), ["site_id"], unique=False)
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rack_face", sa.String(length=10), server_default="",
                                      nullable=False))
        batch_op.add_column(sa.Column("rack_depth", sa.String(length=10), server_default="",
                                      nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_column("rack_depth")
        batch_op.drop_column("rack_face")
    with op.batch_alter_table("site_locations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_site_locations_site_id"))
    op.drop_table("site_locations")
