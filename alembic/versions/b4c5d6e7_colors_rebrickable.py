"""add rebrickable_id column to colors table

Revision ID: b4c5d6e7
Revises: a3b4c5d6
Create Date: 2026-07-14 00:00:00.000000

Cross-references the colors table (keyed by bl_id) against Rebrickable's
/lego/colors/ API via external_ids.BrickLink.ext_ids, matching the existing
bl_id/bl_name and lego_id/lego_name column-pair convention. Additive only —
does not touch bl_id/bl_name/lego_id/lego_name/hex. See
scripts/backfill_rebrickable_colors.py for the backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7"
down_revision: Union[str, None] = "a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("colors", sa.Column("rebrickable_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("colors", "rebrickable_id")
