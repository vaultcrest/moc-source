"""add lego_sets for Rebrickable sets.csv import (offline set catalog + years)

Revision ID: a7b8c9d0
Revises: f6a7b8c9
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0"
down_revision: Union[str, None] = "f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lego_sets",
        sa.Column("set_num", sa.String(30), primary_key=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("theme_id", sa.Integer, nullable=True),
        sa.Column("num_parts", sa.Integer, nullable=True),
        sa.Column("img_url", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("lego_sets")
