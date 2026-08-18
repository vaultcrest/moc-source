"""add mold succession groups + members tables

Revision ID: c4d5e6f7
Revises: b3c4d5e6
Create Date: 2026-08-17 00:00:00.000000

Derived/computed data, not raw ingested data -- these tables hold the
transitive closure of bricklink_alternates (direct alternate_no pairs) and
brickstore_mold_relationship_members (similar_mold groups), which are not
transitively closed on their own (confirmed live 2026-08-17: a direct
lookup on part 15712 misses 12825, which is only an alternate of 2555, two
hops away). See scripts/compute_mold_succession.py, which fully
truncates+reinserts both tables each run -- there is no incremental writer.

last_used_year/year_released are denormalized snapshots from
bl_part_catalog at compute time (same reasoning
brickstore_mold_relationship_members already uses for its own category_id
copy, instead of requiring a join back on every read).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7"
down_revision: Union[str, None] = "b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mold_succession_groups",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("computed_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "mold_succession_members",
        sa.Column("group_id", sa.BigInteger,
                  sa.ForeignKey("mold_succession_groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("part_no", sa.String(100), primary_key=True),
        sa.Column("last_used_year", sa.Integer, nullable=True),
        sa.Column("year_released", sa.Integer, nullable=True),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_mold_succession_members_part_no", "mold_succession_members", ["part_no"])


def downgrade() -> None:
    op.drop_index("ix_mold_succession_members_part_no", table_name="mold_succession_members")
    op.drop_table("mold_succession_members")
    op.drop_table("mold_succession_groups")
