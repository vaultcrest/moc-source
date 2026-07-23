"""add year column to brickstore_minifig_catalog

Revision ID: f0a1b2c3
Revises: e9f0a1b2
Create Date: 2026-07-23 02:00:00.000000

brickstore_minifig_catalog had no release-year column at all -- found
2026-07-23 while reviewing a manually-downloaded BrickLink catalog file
(Minifigures.xml, from BrickLink's own authenticated catalog download page)
that carries an ITEMYEAR field per minifig_no BrickLink itself doesn't
expose anywhere else this project already ingests. Named `year` to match
lego_sets.year's existing convention (bl_part_catalog uses
year_released/last_used_year instead, but that's a part-specific pair
tracking two different signals -- a minifig, like a set, has one release
year).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3"
down_revision: Union[str, None] = "e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brickstore_minifig_catalog",
        sa.Column("year", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brickstore_minifig_catalog", "year")
