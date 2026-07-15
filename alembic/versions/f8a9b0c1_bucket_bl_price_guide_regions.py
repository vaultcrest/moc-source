"""bucket bl_price_guide_monthly into global/north_america/eu_gb/other

Revision ID: f8a9b0c1
Revises: e7f8a9b0
Create Date: 2026-07-15 00:00:00.000000

scrape_bl_price_guide.py no longer restricts BrickLink's Price Guide call to
region=north_america -- it fetches worldwide (same 2 calls/pair) and buckets
seller_country_code into 4 groups itself: global (every row, unfiltered --
the superset), north_america, eu_gb, and other (see
scripts/_price_guide_regions.py). One scrape now covers all 4 groups in a
single pass, so bl_price_guide_scan_log no longer needs region as part of
its identity -- one row per (part_no, color_id) is enough.

Only ~1,250 of ~80,894 pairs had been scraped under the old NA-only scheme
as of this migration (this first pass started 2026-07-15), all under
region='north_america' -- truncating both tables and restarting the first
pass clean is simpler than trying to backfill eu_gb/other for that tiny
slice in place.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1"
down_revision: Union[str, None] = "e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("TRUNCATE TABLE bl_price_guide_monthly")

    op.drop_table("bl_price_guide_scan_log")
    op.create_table(
        "bl_price_guide_scan_log",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bl_price_guide_scan_log")
    op.create_table(
        "bl_price_guide_scan_log",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.String(30), primary_key=True),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
    )
    # bl_price_guide_monthly's TRUNCATE is not reversible -- data-only, left as-is.
