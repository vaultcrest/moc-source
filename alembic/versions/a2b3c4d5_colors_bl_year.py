"""add bl_year_from/bl_year_to columns to colors

Revision ID: a2b3c4d5
Revises: f0a1b2c3
Create Date: 2026-07-26 00:00:00.000000

colors.rebrickable_year_from/_to (added by backfill_rebrickable_colors.py)
turned out to disagree with BrickLink's own year data for 73 of 218 colors,
by as much as 48 years (e.g. Medium Blue: Rebrickable says 1997, BrickLink
says 1949 -- confirmed live via a real part/set, bslot02 in set 700-12, a
1949-era Danish "Automatic Binding Bricks" gift set). Root cause: Rebrickable's
year_from likely reflects the earliest SET REBRICKABLE HAS INVENTORIED with
that color, which undercounts colors whose early usage was mostly in
single-part gift/refill sets Rebrickable's inventory coverage is thin on.

BrickLink's own year data (COLORYEARFROM/COLORYEARTO in colors.xml, part of
BrickStore's own bulk catalog extraction we already download weekly -- see
_brickstore_release.py) is the more authoritative source, per the same
"treat BrickLink as source of truth" call already applied to codes.xml-based
corrections. Kept as separate bl_year_from/bl_year_to columns rather than
overwriting rebrickable_year_from/_to, since that column name documents its
own provenance and overwriting it would misrepresent where the data came
from.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5"
down_revision: Union[str, None] = "f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("colors", sa.Column("bl_year_from", sa.Integer, nullable=True))
    op.add_column("colors", sa.Column("bl_year_to", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("colors", "bl_year_to")
    op.drop_column("colors", "bl_year_from")
