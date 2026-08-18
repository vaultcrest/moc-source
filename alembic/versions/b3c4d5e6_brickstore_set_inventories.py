"""add brickstore set catalog + set inventory tables

Revision ID: b3c4d5e6
Revises: a2b3c4d5
Create Date: 2026-08-17 00:00:00.000000

The BrickStore public release already includes a full Sets catalog
(items/S.xml, with ITEMYEAR) and per-set part inventories (S/<set_num>.xml,
21,015 files as of 2026-08-17) in the same release we already download for
parts/minifigs -- confirmed present on disk but never ingested. Same shape
as brickstore_minifig_catalog/brickstore_minifig_inventory_items.

Motivation: last_used_year for a meaningful slice of bl_part_catalog can't
be resolved via the existing Rebrickable-chain backfills (no bricklink_mappings
row, or Rebrickable has no record under any part_no) -- 1,042 parts confirmed
stuck as of this migration. This data lets last_used_year be derived
directly from BrickLink-lineage data (max ITEMYEAR across every set
containing a part_no), no API calls, no Rebrickable dependency.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6"
down_revision: Union[str, None] = "a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brickstore_set_catalog",
        sa.Column("set_num", sa.String(30), primary_key=True),
        sa.Column("category_id", sa.Integer, nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("imported_at", sa.DateTime, nullable=False),
        sa.Column("inventory_imported_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "brickstore_set_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("set_num", sa.String(30),
                  sa.ForeignKey("brickstore_set_catalog.set_num", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer, nullable=True),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("is_extra", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_alternate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("match_id", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_counterpart", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_brickstore_set_inventory_items_set_num",
                     "brickstore_set_inventory_items", ["set_num"])
    op.create_index("ix_brickstore_set_inventory_items_part_no",
                     "brickstore_set_inventory_items", ["part_no"])


def downgrade() -> None:
    op.drop_index("ix_brickstore_set_inventory_items_part_no",
                   table_name="brickstore_set_inventory_items")
    op.drop_index("ix_brickstore_set_inventory_items_set_num",
                   table_name="brickstore_set_inventory_items")
    op.drop_table("brickstore_set_inventory_items")
    op.drop_table("brickstore_set_catalog")
