"""add hex column to colors table

Revision ID: e5f6a7b8
Revises: d4e5f6a7
Create Date: 2026-06-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8"
down_revision: Union[str, None] = "d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("colors", sa.Column("hex", sa.String(6), nullable=True))


def downgrade() -> None:
    op.drop_column("colors", "hex")
