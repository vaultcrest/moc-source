"""drop bl_part_catalog.supersets_count

Revision ID: a3b4c5d6
Revises: f2a3b4c5
Create Date: 2026-07-14 00:00:00.000000

supersets_count (added in e1f2a3b4) existed solely to distinguish "BrickLink
confirms this part was never in any set" from "BrickLink found sets but none
matched our local lego_sets snapshot" — a gap-diagnosis signal for
last_used_year. last_used_year is now sourced from Rebrickable's bulk parts
API instead (scripts/backfill_last_used_year.py), which doesn't depend on
lego_sets at all, so that gap can't occur anymore and nothing reads this
column (confirmed via grep — no router/frontend consumer).
scrape_bl_mold_data.py has already stopped writing to it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6"
down_revision: Union[str, None] = "f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("bl_part_catalog", "supersets_count")


def downgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("supersets_count", sa.Integer, nullable=True))
