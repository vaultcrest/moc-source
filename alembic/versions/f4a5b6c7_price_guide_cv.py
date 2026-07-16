"""add price_cv to bl_price_guide_velocity

Revision ID: f4a5b6c7
Revises: e3f4a5b6
Create Date: 2026-07-16 13:00:00.000000

Price volatility signal alongside the existing avg_monthly_qty "quick
movers" stat -- coefficient of variation (population stdev / mean) of the
pooled, outlier-filtered per-sale unit prices a single scrape call returns
(up to ~6 months at once), not stddev of the monthly averages already
stored in bl_price_guide_monthly. Computed in-memory by
scrape_bl_price_guide.py from data it already fetches, no new BL calls.
Refreshed each run, same as avg_monthly_qty -- not tracked as its own
month-to-month trend, since there's no established value in that yet.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7"
down_revision: Union[str, None] = "e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_price_guide_velocity", sa.Column("price_cv", sa.Numeric, nullable=True))


def downgrade() -> None:
    op.drop_column("bl_price_guide_velocity", "price_cv")
