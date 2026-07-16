#!/usr/bin/env python3
"""Ingests per-minifig component breakdowns (part_no/color_id/qty) from the
BrickStore public release's M/<minifig_no>.xml files into
brickstore_minifig_inventory_items.

Foundation for a future minifig build-cost calculator (not built in this
pass) -- summing PAB and/or BL Price Guide cost across a minifig's
components. Resumable via brickstore_minifig_catalog.inventory_imported_at,
a dedicated gate separate from imported_at (the mold_backfilled_at vs
looked_up_at lesson from earlier in this project) -- first run processes
every minifig (17,106 as of 2026-07-15, no external rate limit since these
are local files already downloaded), later runs only pick up minifigs added
by a subsequent catalog refresh.

Usage:
    DATABASE_URL=... python scripts/ingest_brickstore_minifig_inventories.py
    DATABASE_URL=... python scripts/ingest_brickstore_minifig_inventories.py --data-dir /path/to/extracted
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from _brickstore_release import ensure_latest, iter_minifig_inventory_files
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

INSERT_ITEMS_SQL = """
    INSERT INTO brickstore_minifig_inventory_items
        (minifig_no, item_type, part_no, color_id, qty, is_extra, is_alternate, match_id, is_counterpart)
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

    cur.execute("SELECT minifig_no FROM brickstore_minifig_catalog WHERE inventory_imported_at IS NULL")
    pending = {r[0] for r in cur.fetchall()}
    print(f"{len(pending)} minifig(s) pending inventory import")

    now = datetime.now(timezone.utc)
    processed = 0
    total_items = 0

    for minifig_no, items in iter_minifig_inventory_files(extract_dir):
        if minifig_no not in pending:
            continue

        if args.dry_run:
            print(f"    [dry-run] {minifig_no}: {len(items)} component(s)")
        else:
            if items:
                psycopg2.extras.execute_values(
                    cur, INSERT_ITEMS_SQL,
                    [(minifig_no, it["item_type"], it["part_no"], it["color_id"], it["qty"],
                      it["is_extra"], it["is_alternate"], it["match_id"], it["is_counterpart"])
                     for it in items],
                )
            cur.execute(
                "UPDATE brickstore_minifig_catalog SET inventory_imported_at = %s WHERE minifig_no = %s",
                (now, minifig_no),
            )
        processed += 1
        total_items += len(items)
        if processed % 1000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  ...{processed}/{len(pending)} processed", flush=True)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s. Minifigs processed: {processed}, component rows: {total_items}")


if __name__ == "__main__":
    main()
