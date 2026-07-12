"""add mold_backfilled_at to bl_part_catalog — dedicated resumability marker

Revision ID: c9d0e1f2
Revises: b8c9d0e1
Create Date: 2026-07-12 00:00:00.000000

The pre-existing looked_up_at column is also set by the unrelated live-request
cache path in routers/parts.py (which never touches last_used_year). Using
looked_up_at as the mold-backfill resumability gate caused parts already
cached by that older path to be silently skipped forever, permanently stuck
at last_used_year = NULL even though they were never actually attempted by
scripts/scrape_bl_mold_data.py. This dedicated column decouples the two.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2"
down_revision: Union[str, None] = "b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("mold_backfilled_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "mold_backfilled_at")
