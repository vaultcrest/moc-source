"""add live-BL minifig inventory + price guide tables

Revision ID: e6f7a8b9
Revises: d5e6f7a8
Create Date: 2026-08-18 00:00:00.000000

BrickLink's live API confirmed 2026-08-18 to support per-minifig catalog
lookups that brickstore_minifig_inventory_items (bulk BrickStore export)
and the queued Rebrickable/set-crawl plan (README What's Next #10) don't
cover as directly:

  - GET /items/MINIFIG/{no}/subsets returns real BL-native part_no/color_id
    inventory directly, no Rebrickable numbering translation needed.
  - GET /items/MINIFIG/{no}/price?guide_type=sold&new_or_used=N|U returns
    sold-listing price history, same shape as the existing parts Price
    Guide (bl_price_guide_monthly).

minifig_inventory_items is a new, separate table from the existing
brickstore_minifig_inventory_items ("reference table", bulk-sourced,
untouched by this work) -- this one is live-BL-sourced and refreshable.
bl_minifig_price_guide_monthly mirrors bl_price_guide_monthly's exact
column shape, keyed by minifig_no instead of (part_no, color_id).

No separate scan_log table -- brickstore_minifig_catalog already tracks
per-source completion via inventory_imported_at/rb_inventory_imported_at,
so this adds two more markers on the same table rather than introducing
a new resumability pattern.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9"
down_revision: Union[str, None] = "d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brickstore_minifig_catalog", sa.Column("bl_inventory_imported_at", sa.DateTime, nullable=True))
    op.add_column("brickstore_minifig_catalog", sa.Column("bl_price_scanned_at", sa.DateTime, nullable=True))

    op.create_table(
        "minifig_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("minifig_no", sa.String(100),
                  sa.ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), nullable=False),
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("extra_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_alternate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_counterpart", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("match_no", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_minifig_inventory_items_minifig_no", "minifig_inventory_items", ["minifig_no"])
    op.create_index("ix_minifig_inventory_items_part_no", "minifig_inventory_items", ["part_no"])

    op.create_table(
        "bl_minifig_price_guide_monthly",
        sa.Column("minifig_no", sa.String(100),
                  sa.ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), primary_key=True),
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


def downgrade() -> None:
    op.drop_table("bl_minifig_price_guide_monthly")
    op.drop_index("ix_minifig_inventory_items_part_no", table_name="minifig_inventory_items")
    op.drop_index("ix_minifig_inventory_items_minifig_no", table_name="minifig_inventory_items")
    op.drop_table("minifig_inventory_items")
    op.drop_column("brickstore_minifig_catalog", "bl_price_scanned_at")
    op.drop_column("brickstore_minifig_catalog", "bl_inventory_imported_at")
