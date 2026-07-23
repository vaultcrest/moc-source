"""add lego_set_inventory_items table

Revision ID: c2d3e4f5
Revises: b6c7d8e9
Create Date: 2026-07-22 00:00:00.000000

Set-level part inventories from Rebrickable's bulk inventories.csv +
inventory_parts.csv (scripts/import_rebrickable_set_inventories.py). Found
2026-07-22: BrickStore's S/ bulk XML files (already used for minifig
inventories) only cover 20,930 of our 27,318 known sets (76.6%) -- 10,153
sets had zero part-inventory data anywhere. Rebrickable's own bulk data is
the same origin as lego_sets itself, verified live against 5 real sets to
match Rebrickable's live /lego/sets/{set_num}/parts/ API exactly (row
counts and individual part/qty pairs), so it should cover close to 100%
instead of ~77%.

rb_part_num stores Rebrickable's OWN part numbering, deliberately NOT
translated to a BrickLink part number -- there is no existing direct
Rebrickable-part_num -> BL-part_no lookup table (bricklink_mappings is
keyed by element_id, not part_num-to-part_num), and writing Rebrickable's
numbering into anything resembling a BL-part_no column is the exact
mistake the 2026-07-14 bricklink_mappings corruption bug (29,689 untranslated
rows) taught this project to avoid. bl_color_id is translated via
colors.rebrickable_id at import time (nullable -- rows are kept even when
unmapped, since dropping them would make the inventory silently
incomplete).

inventory_imported_at on lego_sets is the resumability gate, same pattern
as brickstore_minifig_catalog.inventory_imported_at (b0c1d2e3) -- a
dedicated column separate from lego_sets.updated_at, so re-running the
import only processes newly-added sets.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5"
down_revision: Union[str, None] = "b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lego_sets",
        sa.Column("inventory_imported_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "lego_set_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("set_num", sa.String(30),
                  sa.ForeignKey("lego_sets.set_num", ondelete="CASCADE"), nullable=False),
        sa.Column("rb_part_num", sa.Text, nullable=False),
        sa.Column("rb_color_id", sa.Integer, nullable=False),
        sa.Column("bl_color_id", sa.Integer, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("is_spare", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("inventory_version", sa.Integer, nullable=False),
    )
    op.create_unique_constraint(
        "uq_lego_set_inventory_items_set_part_color_spare",
        "lego_set_inventory_items",
        ["set_num", "rb_part_num", "rb_color_id", "is_spare"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lego_set_inventory_items_set_part_color_spare",
        "lego_set_inventory_items",
        type_="unique",
    )
    op.drop_table("lego_set_inventory_items")
    op.drop_column("lego_sets", "inventory_imported_at")
