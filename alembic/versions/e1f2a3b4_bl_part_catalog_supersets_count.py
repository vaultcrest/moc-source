"""add supersets_count to bl_part_catalog + restore mold-backfill progress

Revision ID: e1f2a3b4
Revises: d0e1f2a3
Create Date: 2026-07-13 00:00:00.000000

Two things bundled into one deploy:

1. `supersets_count` — the raw count of SET numbers BrickLink's supersets
   endpoint returned for a part_no, stored regardless of whether any of
   them matched a row in `lego_sets`. Without this, a NULL `last_used_year`
   is ambiguous: it could mean "BrickLink confirms this part was never in
   any set" (supersets_count = 0, a trustworthy negative) or "BrickLink
   says it WAS in sets, but none matched our local lego_sets snapshot"
   (supersets_count > 0, a real data gap worth chasing). Previously that
   distinction only existed transiently in a run's console/email output;
   this makes it a permanently queryable per-row fact.

2. Data backfill for `mold_backfilled_at` (added in c9d0e1f2). That
   migration only added the column — it never populated it for rows
   already legitimately processed by scripts/scrape_bl_mold_data.py,
   which reset the backfill's resumability queue back to nearly the full
   `bl_part_catalog` universe instead of just the ~1,603 rows the fix was
   meant to target.

   Distinguishing signal: scrape_bl_mold_data.py's main() computes
   `now = datetime.now(timezone.utc)` once per run, before the loop, and
   reuses that single value as `looked_up_at` for every part processed in
   that run. So every row touched by one nightly batch shares the exact
   same (microsecond-precision) `looked_up_at` timestamp. The unrelated
   live-request cache path in routers/parts.py always uses a fresh
   `datetime.utcnow()` per individual request, so its rows have singleton
   timestamps. Rows whose `looked_up_at` is shared by more than one row
   were therefore part of a real backfill batch and are marked done;
   singleton-timestamp rows (including the original ~1,603 stuck ones)
   are left NULL so they correctly re-enter the queue.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4"
down_revision: Union[str, None] = "d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bl_part_catalog", sa.Column("supersets_count", sa.Integer, nullable=True))

    op.execute("""
        WITH batch_timestamps AS (
            SELECT looked_up_at
            FROM bl_part_catalog
            WHERE looked_up_at IS NOT NULL
            GROUP BY looked_up_at
            HAVING count(*) > 1
        )
        UPDATE bl_part_catalog b
        SET mold_backfilled_at = b.looked_up_at
        FROM batch_timestamps bt
        WHERE b.looked_up_at = bt.looked_up_at
          AND b.mold_backfilled_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column("bl_part_catalog", "supersets_count")
    # The mold_backfilled_at restore is data-only and not meaningfully
    # reversible — undoing it would just re-trigger the progress-reset
    # regression this migration fixes. Left as-is.
