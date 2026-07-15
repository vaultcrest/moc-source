"""add bl_price_guide_monthly and bl_price_guide_scan_log

Revision ID: e7f8a9b0
Revises: d6e7f8a9
Create Date: 2026-07-15 00:00:00.000000

BrickLink Price Guide monthly history (North America, sold, New+Used).
bl_price_guide_monthly holds one outlier-filtered avg/min/max/median row per
(part_no, color_id, region, new_or_used, month) -- populated by bucketing
each scrape's price_detail[] by month(date_ordered), per
scripts/scrape_bl_price_guide.py. No retention limit: rows are kept
indefinitely to build multi-year price-trend history, never purged.

bl_price_guide_scan_log is a separate thin resumability tracker (one row per
(part_no, color_id, region) once scraped) so pairs with zero BL sales still
get marked done instead of being retried every run -- bl_price_guide_monthly
itself can't serve as the completion signal since a zero-sales pair produces
no rows there at all.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0"
down_revision: Union[str, None] = "d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bl_price_guide_monthly",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.String(30), primary_key=True),
        sa.Column("new_or_used", sa.String(1), primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("avg_price_cents", sa.Integer, nullable=True),
        sa.Column("min_price_cents", sa.Integer, nullable=True),
        sa.Column("max_price_cents", sa.Integer, nullable=True),
        sa.Column("median_price_cents", sa.Integer, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=True),
        sa.Column("raw_sample_count", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "bl_price_guide_scan_log",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.String(30), primary_key=True),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bl_price_guide_scan_log")
    op.drop_table("bl_price_guide_monthly")
