"""add last_used_year to bl_part_catalog for mold-succession detection

Revision ID: b8c9d0e1
Revises: a7b8c9d0
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1"
down_revision: Union[str, None] = "a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("last_used_year", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "last_used_year")
