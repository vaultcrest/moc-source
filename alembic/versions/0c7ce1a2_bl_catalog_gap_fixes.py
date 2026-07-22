"""add bl_catalog_gap_fixes tracking table

Revision ID: 0c7ce1a2
Revises: fbe2ca73
Create Date: 2026-07-21 00:00:00.000000

Tracks scripts/reverse_map_bl_catalog.py's resumable retry queue for real
BrickLink part_nos that have zero bricklink_mappings row at all (found
2026-07-21: ~52,528 of ~95,554 BrickLink parts, since import_rebrickable.py
only writes a row when Rebrickable's data already has a translation --
untranslated parts are silently skipped, never written). This is the
opposite direction from rebrickable_part_no_fixes, which repairs existing-
but-wrong rows; this table is for parts that were never attempted at all.

Keyed by the BrickLink part_no (old_part_no, matching rebrickable_part_no_
fixes' naming for consistency even though there's no "old" numbering here --
it's just the part_no being retried). is_printed classifies each candidate
at first-seen time (by bl_categories.category_name and part_no suffix
pattern) so the priority queue can exhaust plain parts before printed/
decorated ones (Sean's explicit call 2026-07-21 -- printed variants are both
the largest share of the gap and the hardest to resolve, since Rebrickable/
BrickLink numbering divergence concentrates almost entirely there).

Same "never permanently done" philosophy as rebrickable_part_no_fixes --
unresolved stays retry-eligible, deprioritized behind never-attempted rows
within its own is_printed tier, since Rebrickable's catalog keeps growing.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0c7ce1a2"
down_revision: Union[str, None] = "fbe2ca73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bl_catalog_gap_fixes",
        sa.Column("old_part_no", sa.String(100), primary_key=True),
        sa.Column("rb_part_num", sa.String(100), nullable=True),
        sa.Column("is_printed", sa.Boolean, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),  # 'reverse_lookup' or 'unresolved'
        sa.Column("elements_created", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempted_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_bl_catalog_gap_fixes_priority",
        "bl_catalog_gap_fixes",
        ["is_printed", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bl_catalog_gap_fixes_priority", table_name="bl_catalog_gap_fixes")
    op.drop_table("bl_catalog_gap_fixes")
