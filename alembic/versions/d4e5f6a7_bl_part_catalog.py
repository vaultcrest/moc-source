"""add bl_part_catalog for caching BrickLink catalog lookups

Revision ID: d4e5f6a7
Revises: c3d4e5f6
Create Date: 2026-06-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7"
down_revision: Union[str, None] = "c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bl_part_catalog",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("item_type", sa.String(20), nullable=True),
        sa.Column("looked_up_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bl_part_catalog")
