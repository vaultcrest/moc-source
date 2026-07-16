"""add brickstore_* catalog, minifig, and inventory tables

Revision ID: b0c1d2e3
Revises: a9b0c1d2
Create Date: 2026-07-16 00:00:00.000000

Ingests BrickLink's own bulk catalog data via the public, unauthenticated
GitHub Release published by BrickStore's maintainer (github.com/rgriebl/
brickstore-database) -- a legitimate mirror of BrickLink's authenticated
catalogDownload.asp bulk-export feature, which we have no partner credential
for ourselves. See scripts/_brickstore_release.py and
scripts/ingest_brickstore_catalog.py.

brickstore_part_catalog / brickstore_minifig_catalog are the full BrickLink
Parts/Minifigure catalogs (part_no / minifig_no as real BrickLink item
numbers) -- distinct from bricklink_mappings (our own curated, naturally
partial subset with LEGO element_id/PAB pricing attached) and bl_part_catalog
(the live-API-lookup cache). Minifigs have no LEGO element_id (never sold
individually via PAB) so get their own parallel table, not folded into
bricklink_mappings/lego_elements.

Inventory item tables (minifig components, and part-assembly components e.g.
a bicycle part broken into frame + tires) reference brickstore_part_catalog,
not bricklink_mappings -- PAB and BL Price Guide pricing resolve via two
independent paths (PAB needs bricklink_mappings -> element_id ->
lego_element_prices; BL Price Guide joins bl_price_guide_monthly directly on
part_no/color_id) and gating inventory ingestion on bricklink_mappings
coverage would be circular, since growing that coverage is part of the point.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3"
down_revision: Union[str, None] = "a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brickstore_part_catalog",
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("category_id", sa.Integer, nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("alternate_item_ids", sa.Text, nullable=True),
        sa.Column("imported_at", sa.DateTime, nullable=False),
        sa.Column("inventory_imported_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "brickstore_minifig_catalog",
        sa.Column("minifig_no", sa.String(100), primary_key=True),
        sa.Column("category_id", sa.Integer, nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("imported_at", sa.DateTime, nullable=False),
        sa.Column("inventory_imported_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "brickstore_minifig_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("minifig_no", sa.String(100),
                  sa.ForeignKey("brickstore_minifig_catalog.minifig_no", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer, nullable=True),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("is_extra", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_alternate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("match_id", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_counterpart", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_brickstore_minifig_inventory_items_minifig_no",
                     "brickstore_minifig_inventory_items", ["minifig_no"])

    op.create_table(
        "brickstore_part_assembly_inventory_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("parent_part_no", sa.String(100),
                  sa.ForeignKey("brickstore_part_catalog.part_no", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("part_no", sa.String(100), nullable=False),
        sa.Column("color_id", sa.Integer, nullable=True),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("is_extra", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_alternate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("match_id", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_counterpart", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_brickstore_part_assembly_inventory_items_parent_part_no",
                     "brickstore_part_assembly_inventory_items", ["parent_part_no"])


def downgrade() -> None:
    op.drop_index("ix_brickstore_part_assembly_inventory_items_parent_part_no",
                   table_name="brickstore_part_assembly_inventory_items")
    op.drop_table("brickstore_part_assembly_inventory_items")
    op.drop_index("ix_brickstore_minifig_inventory_items_minifig_no",
                   table_name="brickstore_minifig_inventory_items")
    op.drop_table("brickstore_minifig_inventory_items")
    op.drop_table("brickstore_minifig_catalog")
    op.drop_table("brickstore_part_catalog")
