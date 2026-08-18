"""add ldraw_id/ldraw_name to colors

Revision ID: d5e6f7a8
Revises: c4d5e6f7
Create Date: 2026-08-18 00:00:00.000000

BrickLink color id -> LDraw color id mapping, needed for generating Studio
palette files directly from this DB (Studio palette entries are keyed by
LDraw color id, not BrickLink's own id -- confirmed live 2026-08-18 reading
brick_palettes_generator's resolve_studio_color()). Same shape as the
existing bl_id/lego_id/rebrickable_id columns. Backfilled one-time from
brick_palettes_generator/data/color_database.json's bricklink.<id>.ldraw
field (174 entries) by scripts/backfill_ldraw_colors.py -- not a recurring
job, that reference file only changes when Sean updates it by hand.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8"
down_revision: Union[str, None] = "c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("colors", sa.Column("ldraw_id", sa.Integer, nullable=True))
    op.add_column("colors", sa.Column("ldraw_name", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("colors", "ldraw_name")
    op.drop_column("colors", "ldraw_id")
