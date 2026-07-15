"""add color_type and rebrickable year range to colors table

Revision ID: c5d6e7f8
Revises: b4c5d6e7
Create Date: 2026-07-14 00:00:00.000000

Additive only — does not touch bl_id/bl_name/lego_id/lego_name/hex/
rebrickable_id. color_type is BrickLink's own color category (Solid,
Transparent, Modulex, Pearl, Chrome, Satin, Glitter, Metallic, Milky,
Speckle), see scripts/backfill_bricklink_colors.py. rebrickable_year_from/
_to are Rebrickable's first/last observed usage year for that color across
any part, sourced from Rebrickable's bulk colors.csv download (not exposed
by the live REST API — confirmed 2026-07-14), see
scripts/backfill_rebrickable_colors.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8"
down_revision: Union[str, None] = "b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("colors", sa.Column("color_type", sa.Text(), nullable=True))
    op.add_column("colors", sa.Column("rebrickable_year_from", sa.Integer(), nullable=True))
    op.add_column("colors", sa.Column("rebrickable_year_to", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("colors", "rebrickable_year_to")
    op.drop_column("colors", "rebrickable_year_from")
    op.drop_column("colors", "color_type")
