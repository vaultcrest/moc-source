"""add rebrickable_part_no_fixes tracking table

Revision ID: f2a3b4c5
Revises: e1f2a3b4
Create Date: 2026-07-14 00:00:00.000000

Tracks the one-time correction pass for bricklink_mappings.part_no rows
that were written with Rebrickable's own print-variant numbering (e.g.
"27372pr0006") instead of a real BrickLink part number (e.g. "27372pb06")
-- root-caused 2026-07-14 to three independent write paths that each read
the wrong field out of Rebrickable's API/CSV data.

Keyed by the OLD (bad) part_no so a row naturally drops out of
scripts/fix_rebrickable_part_nos.py's work queue once corrected. Deliberately
does NOT use a "resolved forever" boolean gate the way bl_part_catalog.
mold_backfilled_at does -- an `unresolved` row must stay retry-eligible
(just deprioritized behind never-attempted rows), since Rebrickable's own
data changes over time and a miss today isn't a permanent fact.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5"
down_revision: Union[str, None] = "e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rebrickable_part_no_fixes",
        sa.Column("old_part_no", sa.String(100), primary_key=True),
        sa.Column("new_part_no", sa.String(100), nullable=True),
        sa.Column("method", sa.String(20), nullable=False),  # 'bulk', 'element_fallback', or 'unresolved'
        sa.Column("attempted_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rebrickable_part_no_fixes")
