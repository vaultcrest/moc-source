"""add minifig_mappings + rebrickable_minifig_inventory_items tables

Revision ID: e9f0a1b2
Revises: c2d3e4f5
Create Date: 2026-07-23 00:00:00.000000

BrickStore's M/ bulk XML files (ingest_brickstore_minifig_inventories.py)
only cover 17,106 of 19,054 known minifigs (89.8%) -- 1,948 minifigs have
no part-inventory data anywhere. Unlike lego_sets (c2d3e4f5), Rebrickable's
minifig data can't be joined in for free: BrickLink's minifig_no (e.g.
hp637) and Rebrickable's fig_num (e.g. fig-017719) are unrelated numbering
schemes -- confirmed live 2026-07-22/23 that Rebrickable's own APIs expose
no BrickLink cross-reference for minifigs (unlike parts, which do carry
external_ids), and that exact name matching only resolves ~10% of pairs,
with some of those already ambiguous.

minifig_mappings bridges the two via the one thing both catalogs share:
set_num. Rebrickable's inventory_minifigs.csv says which fig_nums are in a
set; BrickLink's GET /items/SET/{no}/subsets (BLClient.fetch_subsets, added
alongside this migration) says which minifig_nos are in the same set.
scripts/map_rebrickable_minifigs.py resolves pairs per-set (direct when a
set has exactly one minifig on both sides, name-token-overlap disambiguation
otherwise) and writes the result here. UNIQUE on both fig_num and
minifig_no -- a real mapping is 1:1 in both directions.

rebrickable_minifig_inventory_items mirrors lego_set_inventory_items
(c2d3e4f5) but is keyed by minifig_no (post-mapping) rather than fig_num,
so it sits in the same identity space as brickstore_minifig_inventory_items
(b0c1d2e3) and can be directly diffed against it for conflicts. rb_part_num
is deliberately untranslated for the same reason as lego_set_inventory_items
-- see that migration's docstring.

minifig_mapping_scan_log is a thin per-set resumability tracker, same
rationale as bl_price_guide_scan_log: a set that resolves zero mapping
pairs (ambiguous, or its minifigs are already mapped via another set)
still needs to be marked scanned, or it would be retried forever.

brickstore_minifig_catalog.rb_inventory_imported_at is the resumability
gate for scripts/import_rebrickable_minifig_inventories.py, same pattern
as lego_sets.inventory_imported_at (c2d3e4f5) -- named rb_-prefixed and
kept separate from that table's existing inventory_imported_at (which
tracks the BrickStore-sourced import, a different pipeline entirely).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2"
down_revision: Union[str, None] = "c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brickstore_minifig_catalog",
        sa.Column("rb_inventory_imported_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "minifig_mappings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("fig_num", sa.Text, nullable=False),
        sa.Column("minifig_no", sa.String(100),
                  sa.ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("matched_via_set_num", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_minifig_mappings_fig_num", "minifig_mappings", ["fig_num"])
    op.create_unique_constraint("uq_minifig_mappings_minifig_no", "minifig_mappings", ["minifig_no"])

    op.create_table(
        "rebrickable_minifig_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("minifig_no", sa.String(100),
                  sa.ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), nullable=False),
        sa.Column("rb_part_num", sa.Text, nullable=False),
        sa.Column("rb_color_id", sa.Integer, nullable=False),
        sa.Column("bl_color_id", sa.Integer, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("inventory_version", sa.Integer, nullable=False),
    )
    op.create_unique_constraint(
        "uq_rebrickable_minifig_inventory_items_minifig_part_color",
        "rebrickable_minifig_inventory_items",
        ["minifig_no", "rb_part_num", "rb_color_id"],
    )

    op.create_table(
        "minifig_mapping_scan_log",
        sa.Column("set_num", sa.String(30), primary_key=True),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_column("brickstore_minifig_catalog", "rb_inventory_imported_at")
    op.drop_table("minifig_mapping_scan_log")
    op.drop_constraint(
        "uq_rebrickable_minifig_inventory_items_minifig_part_color",
        "rebrickable_minifig_inventory_items",
        type_="unique",
    )
    op.drop_table("rebrickable_minifig_inventory_items")
    op.drop_constraint("uq_minifig_mappings_minifig_no", "minifig_mappings", type_="unique")
    op.drop_constraint("uq_minifig_mappings_fig_num", "minifig_mappings", type_="unique")
    op.drop_table("minifig_mappings")
