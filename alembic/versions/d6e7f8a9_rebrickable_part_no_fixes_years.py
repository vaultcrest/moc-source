"""add year_from/year_to to rebrickable_part_no_fixes

Revision ID: d6e7f8a9
Revises: c5d6e7f8
Create Date: 2026-07-14 00:00:00.000000

Additive only. Backs the weekly (current year + prior) / monthly (older)
retry tiering in scripts/fix_rebrickable_part_nos.py's new --year-tier flag
-- year_from/year_to are Rebrickable's own first/last-year-used for the
still-untranslated part_num, from the same bulk /lego/parts/ endpoint
already used to attempt translation (scripts/_rebrickable_lookup.py's
resolve_part_years_bulk()).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9"
down_revision: Union[str, None] = "c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rebrickable_part_no_fixes", sa.Column("year_from", sa.Integer(), nullable=True))
    op.add_column("rebrickable_part_no_fixes", sa.Column("year_to", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("rebrickable_part_no_fixes", "year_to")
    op.drop_column("rebrickable_part_no_fixes", "year_from")
