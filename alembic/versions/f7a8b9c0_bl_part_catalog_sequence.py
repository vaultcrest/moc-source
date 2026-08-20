"""add catalog_sequence to bl_part_catalog

Revision ID: f7a8b9c0
Revises: e6f7a8b9
Create Date: 2026-08-19 00:00:00.000000

BrickLink-distributed Studio palette files (confirmed live 2026-08-19
against a real one, "2028 Wave 1 Palette") are ordered in a way that
doesn't match any derived sort tried so far -- not alphabetical by name,
not by part_no, not by category+name. It DOES match the raw row order of
BrickStore's bulk items/P.xml file, which we already download weekly
(scripts/_brickstore_release.py's iter_part_rows() now yields
catalog_sequence, the 0-based position of each part in that file).
Presumably BrickLink's own internal catalog row order, not otherwise
exposed via the live API. Not guaranteed stable release-to-release, so
this gets refreshed on every weekly ingest like every other column here.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0"
down_revision: Union[str, None] = "e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("catalog_sequence", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "catalog_sequence")
