"""add bl_categories (part-scoped subset) and bl_part_catalog.category_id

Revision ID: a9b0c1d2
Revises: f8a9b0c1
Create Date: 2026-07-15 00:00:00.000000

BrickLink's GET /categories returns one flat 561-row list shared across
every item type (parts, sets, minifigs, books, etc.) -- no item_type field
on the category itself, and the endpoint ignores any type-filter query
param (confirmed live 2026-07-15: type=P / item_type=PART / category_type=P
all return the identical 561 rows). Server-side, there is no way to ask
BrickLink for "just the part categories."

bl_categories is seeded from BrickLink's own Parts-catalog browse page
(catalogList.asp's <SELECT NAME="catID"> options, scraped by hand, not an
API endpoint) instead -- 243 rows, cross-verified live against GET
/categories: every (catID, name) pair matched exactly (0 missing, 0 name
mismatches, 0 id mismatches). This confirms the page's catID values are the
same category_id namespace the API uses, just pre-filtered to parts.

category_id on bl_part_catalog is nullable and NOT constrained to
bl_categories -- BrickLink's fetch_item() response already includes
category_id today (confirmed live) but scripts/_bricklink_lookup.py
discards it; a future backfill pass can populate it for free alongside the
existing mold-data scrape, no new BL calls needed. Some part_no rows may
end up with a category_id outside the 243-row seed (e.g. a part BrickLink
files under a category added since this seed, or -- per the docstring
above -- one of the rare non-part categories, since no live cross-check
prevents that) -- deliberately no FK constraint, so backfill isn't blocked
on keeping bl_categories perfectly current.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2"
down_revision: Union[str, None] = "f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bl_categories",
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("category_id"),
    )
    op.add_column("bl_part_catalog", sa.Column("category_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "category_id")
    op.drop_table("bl_categories")
