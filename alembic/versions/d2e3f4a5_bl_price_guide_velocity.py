"""add bl_price_guide_velocity

Revision ID: d2e3f4a5
Revises: c1d2e3f4
Create Date: 2026-07-16 00:00:00.000000

"Quick movers" signal: one rolled-up average-monthly-sales-quantity figure
per (part_no, color_id, region, new_or_used) -- not a monthly time series
like bl_price_guide_monthly, a single calculated stat. Computed by
scrape_bl_price_guide.py in-memory from the same price_detail[] data it
already fetches each run (raw_sample_count per month it just wrote), no new
BL API calls.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5"
down_revision: Union[str, None] = "c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bl_price_guide_velocity",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.String(30), primary_key=True),
        sa.Column("new_or_used", sa.String(1), primary_key=True),
        sa.Column("avg_monthly_qty", sa.Numeric, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bl_price_guide_velocity")
