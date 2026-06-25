"""initial schema — Phase 1 tables

Revision ID: a1b2c3d4
Revises:
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lego_elements",
        sa.Column("element_id", sa.BigInteger(), nullable=False),
        sa.Column("design_id", sa.String(50), nullable=True),
        sa.Column("lego_name", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("price_formatted", sa.String(20), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("element_id"),
    )
    op.create_index("ix_lego_elements_design_id", "lego_elements", ["design_id"])

    op.create_table(
        "bricklink_mappings",
        sa.Column("element_id", sa.BigInteger(), nullable=False),
        sa.Column("part_no", sa.String(100), nullable=True),
        sa.Column("color_id", sa.Integer(), nullable=True),
        sa.Column("item_type", sa.String(20), nullable=True),
        sa.Column("part_name", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["element_id"], ["lego_elements.element_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("element_id"),
    )
    op.create_index("ix_bricklink_mappings_part_no", "bricklink_mappings", ["part_no"])

    op.create_table(
        "bricklink_alternates",
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("alternate_no", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("part_no", "alternate_no"),
    )

    op.create_table(
        "studio_resolutions",
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("part_file", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column("resolution_method", sa.String(50), nullable=True),
        sa.Column("resolved_from", sa.String(100), nullable=True),
        sa.Column("studio_color_id", sa.Integer(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("part_no"),
    )

    op.create_table(
        "multipacks",
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("definition_source", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("part_no"),
    )

    op.create_table(
        "multipack_components",
        sa.Column("parent_part_no", sa.String(100), nullable=False),
        sa.Column("child_part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("child_item_type", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["parent_part_no"], ["multipacks.part_no"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("parent_part_no", "child_part_no", "color_id"),
    )

    op.create_table(
        "failed_studio_mappings",
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("bricklink_name", sa.Text(), nullable=True),
        sa.Column("lego_name", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("part_no", "color_id"),
    )


def downgrade() -> None:
    op.drop_table("failed_studio_mappings")
    op.drop_table("multipack_components")
    op.drop_table("multipacks")
    op.drop_table("studio_resolutions")
    op.drop_table("bricklink_alternates")
    op.drop_table("bricklink_mappings")
    op.drop_table("lego_elements")
