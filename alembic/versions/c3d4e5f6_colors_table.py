"""add colors table for BrickLink/LEGO color name lookups

Revision ID: c3d4e5f6
Revises: b2c3d4e5
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6"
down_revision: Union[str, None] = "b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "colors",
        sa.Column("bl_id", sa.Integer(), nullable=False),
        sa.Column("bl_name", sa.Text(), nullable=False),
        sa.Column("lego_id", sa.Integer(), nullable=True),
        sa.Column("lego_name", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("bl_id"),
    )


def downgrade() -> None:
    op.drop_table("colors")
