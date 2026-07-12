"""add year_released to bl_part_catalog — mold age, free from the same catalog call

Revision ID: d0e1f2a3
Revises: c9d0e1f2
Create Date: 2026-07-12 00:00:00.000000

BrickLink's catalog endpoint (GET /items/PART/{no}) already returns
year_released alongside alternate_no — previously parsed but discarded.
Useful as a secondary signal alongside last_used_year: distinguishes an old
design still in continuous production from a genuinely newer mold, and
helps tie-break between mold-family siblings that both show a recent
last_used_year.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3"
down_revision: Union[str, None] = "c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("year_released", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "year_released")
