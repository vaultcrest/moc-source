"""add is_low_priority to bl_catalog_gap_fixes

Revision ID: a1b2c3d4
Revises: 0c7ce1a2
Create Date: 2026-07-22 00:00:00.000000

Sean's call 2026-07-22: BrickLink "c" + number suffix parts (e.g. 08010ac01,
08010bc02 -- BrickLink's "Complete assembly" marker) and Baseplate-category
parts are disproportionately represented in the never-mapped gap because
BrickLink itself has superseded/deprecated many of them in favor of newer
part numbers for the same physical assembly (confirmed by hand: 08010ac01 ->
superseded by 265bc01, 08010bc02 -> superseded by 266bc02). A reverse lookup
against Rebrickable's bricklink_id= filter will legitimately find nothing
for a part_no BrickLink no longer considers current, even when Rebrickable
has good data under the replacement number -- so these are much less likely
to resolve per attempt than the plain-part backlog they were previously
mixed into. is_low_priority sinks them behind everything else (both plain
and printed tiers) rather than competing for the same nightly budget.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4"
down_revision: Union[str, None] = "0c7ce1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bl_catalog_gap_fixes",
        sa.Column("is_low_priority", sa.Boolean, nullable=False, server_default="false"),
    )
    op.drop_index("ix_bl_catalog_gap_fixes_priority", table_name="bl_catalog_gap_fixes")
    op.create_index(
        "ix_bl_catalog_gap_fixes_priority",
        "bl_catalog_gap_fixes",
        ["is_low_priority", "is_printed", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bl_catalog_gap_fixes_priority", table_name="bl_catalog_gap_fixes")
    op.create_index(
        "ix_bl_catalog_gap_fixes_priority",
        "bl_catalog_gap_fixes",
        ["is_printed", "attempted_at"],
    )
    op.drop_column("bl_catalog_gap_fixes", "is_low_priority")
