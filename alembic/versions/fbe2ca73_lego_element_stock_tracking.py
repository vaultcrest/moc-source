"""add lego_element_stock_monthly and lego_element_stock_state

Revision ID: fbe2ca73
Revises: f4a5b6c7
Create Date: 2026-07-19 00:00:00.000000

PAB stock-status volatility tracking, per (element_id, region). region is one
of the 3 LOCALE_GROUPS keys (na/eu/kr) from scripts/scrape_pab.py, not raw
locale -- stock is confirmed identical across every locale within a group.

lego_element_stock_monthly holds one accumulating row per (element_id,
region, month): to_in_stock_count / to_out_of_stock_count (directional flip
counts, most elements 0-1/month) and seen_in_stock / seen_out_of_stock
(whether that state was observed at least once that month). Populated
incrementally by scripts/scrape_pab.py's record_stock_events() at scrape
time via an additive ON CONFLICT DO UPDATE (+=, OR), not an overwrite, since
each write is one incremental event rather than a full-month recompute. No
retention limit -- mirrors bl_price_guide_monthly's precedent; row growth
here is trivial by comparison.

lego_element_stock_state is a separate, always-current pointer table (PK
element_id, region, no month dimension): currently_in_stock and
last_seen_in_stock_at (NULL = never observed in stock). Rows are created
lazily on first real observation only -- an element never seen on PAB (e.g.
a mold discontinued decades ago) never gets a row in either table, and "not
in stock, last seen N/A" is the default applied at the query layer when no
row exists, not a materialized row for the full lego_elements universe.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fbe2ca73"
down_revision: Union[str, None] = "f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lego_element_stock_monthly",
        sa.Column("element_id", sa.BigInteger, sa.ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("region", sa.String(10), primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("to_in_stock_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("to_out_of_stock_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("seen_in_stock", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("seen_out_of_stock", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "lego_element_stock_state",
        sa.Column("element_id", sa.BigInteger, sa.ForeignKey("lego_elements.element_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("region", sa.String(10), primary_key=True),
        sa.Column("currently_in_stock", sa.Boolean, nullable=False),
        sa.Column("last_seen_in_stock_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lego_element_stock_state")
    op.drop_table("lego_element_stock_monthly")
