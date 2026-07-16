"""add brickstore mold relationship tables; tag bricklink_alternates by source

Revision ID: c1d2e3f4
Revises: b0c1d2e3
Create Date: 2026-07-16 00:00:00.000000

Mold-family relationship data scraped by BrickStore from BrickLink's own
"Item Relationships" catalog feature (similar_parts_with_similar_molds /
similar_parts_with_different_molds), included in the same bulk GitHub
Release as the catalog data in b0c1d2e3. Kept as real groups (cliques), not
flattened straight to pairwise, since the source data is genuinely grouped
(e.g. 4085/4085a/4085b/4085c/4085d all one family) and that structure is
useful on its own, not just as an intermediate step.

Only 'similar_mold' groups get derived into bricklink_alternates (which
means "directly interchangeable") -- 'different_mold' groups stay in
brickstore_mold_relationship_* only. bricklink_alternates gains `source` so
its three writers (the old live-API alternate_no scrape, this release's
ALTITEMIDS field via ingest_brickstore_catalog.py, and this release's
mold-relationship groups via ingest_brickstore_mold_relationships.py) can
each scope their own delete+reinsert without clobbering the others.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4"
down_revision: Union[str, None] = "b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brickstore_mold_relationship_groups",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("relationship_type", sa.String(20), nullable=False),  # 'similar_mold' | 'different_mold'
        sa.Column("imported_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "brickstore_mold_relationship_members",
        sa.Column("group_id", sa.BigInteger,
                  sa.ForeignKey("brickstore_mold_relationship_groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("category_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_brickstore_mold_relationship_members_part_no",
                     "brickstore_mold_relationship_members", ["part_no"])

    op.add_column("bricklink_alternates", sa.Column("source", sa.String(50), nullable=True))
    op.add_column("bricklink_alternates", sa.Column("updated_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("bricklink_alternates", "updated_at")
    op.drop_column("bricklink_alternates", "source")
    op.drop_index("ix_brickstore_mold_relationship_members_part_no",
                   table_name="brickstore_mold_relationship_members")
    op.drop_table("brickstore_mold_relationship_members")
    op.drop_table("brickstore_mold_relationship_groups")
