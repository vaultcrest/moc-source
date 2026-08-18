#!/usr/bin/env python3
"""Ingests per-set part/minifig inventories (part_no/color_id/qty) from the
BrickStore public release's S/<set_num>.xml files into
brickstore_set_inventory_items. 21,015 sets have an inventory file as of
2026-08-17.

This is the data source for deriving bl_part_catalog.last_used_year purely
from BrickLink-lineage data (max brickstore_set_catalog.year across every
set containing a part_no) for parts the Rebrickable-chain backfills
(backfill_last_used_year.py, backfill_unmapped_part_years.py) can't resolve
-- no bricklink_mappings row, or no Rebrickable record under any part_no.
1,042 parts confirmed stuck on that chain as of 2026-08-17. The actual
last_used_year derivation from this table is a separate follow-up pass, not
done by this script.

Same shape and resumability pattern as
scripts/ingest_brickstore_assembly_inventories.py, gated by
brickstore_set_catalog.inventory_imported_at.

Usage:
    DATABASE_URL=... python scripts/ingest_brickstore_set_inventories.py
    DATABASE_URL=... python scripts/ingest_brickstore_set_inventories.py --data-dir /path/to/extracted
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from _brickstore_release import ensure_latest, iter_set_inventory_files
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

INSERT_ITEMS_SQL = """
    INSERT INTO brickstore_set_inventory_items
        (set_num, item_type, part_no, color_id, qty, is_extra, is_alternate, match_id, is_counterpart)
    VALUES %s
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=None,
                         help="use an already-extracted brickstore-database dir instead of downloading")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    start_time = time.monotonic()

    if args.data_dir:
        extract_dir = args.data_dir
        print(f"Using existing extracted data at {extract_dir}")
    else:
        extract_dir = ensure_latest()
        if extract_dir is None:
            print("No new brickstore-database release to ingest (or fetch failed). Nothing to do.")
            return

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT set_num FROM brickstore_set_catalog WHERE inventory_imported_at IS NULL")
    pending = {r[0] for r in cur.fetchall()}
    print(f"{len(pending)} set(s) pending inventory import")

    now = datetime.now(timezone.utc)
    processed = 0
    total_items = 0

    for set_num, items in iter_set_inventory_files(extract_dir):
        if set_num not in pending:
            continue

        if args.dry_run:
            print(f"    [dry-run] {set_num}: {len(items)} item(s)")
        else:
            if items:
                psycopg2.extras.execute_values(
                    cur, INSERT_ITEMS_SQL,
                    [(set_num, it["item_type"], it["part_no"], it["color_id"], it["qty"],
                      it["is_extra"], it["is_alternate"], it["match_id"], it["is_counterpart"])
                     for it in items],
                )
            cur.execute(
                "UPDATE brickstore_set_catalog SET inventory_imported_at = %s WHERE set_num = %s",
                (now, set_num),
            )
        processed += 1
        total_items += len(items)
        if processed % 1000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  ...{processed} processed", flush=True)

    # Same reasoning as ingest_brickstore_assembly_inventories.py: a set
    # without an S/<set_num>.xml file simply has no inventory data in this
    # release (e.g. very old or gear-only listings) -- mark the rest of
    # `pending` done too so this doesn't rescan the whole catalog every week.
    if not args.dry_run:
        existing_stems = {p.stem for p in (extract_dir / "S").glob("*.xml")}
        remaining = pending - existing_stems
        if remaining:
            psycopg2.extras.execute_values(
                cur,
                "UPDATE brickstore_set_catalog SET inventory_imported_at = data.imported_at "
                "FROM (VALUES %s) AS data (set_num, imported_at) WHERE brickstore_set_catalog.set_num = data.set_num",
                [(s, now) for s in remaining],
            )

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s. Sets processed: {processed}, item rows: {total_items}")


if __name__ == "__main__":
    main()
