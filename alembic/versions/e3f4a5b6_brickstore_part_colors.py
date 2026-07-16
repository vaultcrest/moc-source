"""add brickstore_part_colors

Revision ID: e3f4a5b6
Revises: d2e3f4a5
Create Date: 2026-07-16 12:00:00.000000

Per-part color availability, sourced from the BrickStore release's
part_color_codes.xml (109,249 rows: part_no, color name, LEGO element
CODENAME). Missed in the original brickstore ingestion pass -- this file
wasn't catalogued alongside items/P.xml etc. Only (part_no, color_id) is
kept; the CODENAME/element_id crosswalk in that file is ~93% already
present in bricklink_mappings (cross-checked against 108,532 numeric
CODENAMEs: only 18 would add a new mapping, elements already known via
lego_elements), so it isn't worth a second table for now.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6"
down_revision: Union[str, None] = "d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brickstore_part_colors",
        sa.Column("part_no", sa.String(100), sa.ForeignKey("brickstore_part_catalog.part_no", ondelete="CASCADE"), primary_key=True),
        sa.Column("color_id", sa.Integer, primary_key=True),
        sa.Column("imported_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_brickstore_part_colors_color_id", "brickstore_part_colors", ["color_id"])


def downgrade() -> None:
    op.drop_index("ix_brickstore_part_colors_color_id", table_name="brickstore_part_colors")
    op.drop_table("brickstore_part_colors")
