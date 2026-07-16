#!/usr/bin/env python3
"""Ingests per-part-assembly component breakdowns (part_no/color_id/qty)
from the BrickStore public release's P/<part_no>.xml files into
brickstore_part_assembly_inventory_items. Only ~10,788 of the ~95,310 known
parts are themselves assemblies of other parts (e.g. a bicycle part broken
into frame + 2 tires) -- most parts have no P/<id>.xml file at all, which is
expected, not an error.

Foundation for a future "is it cheaper to buy the whole assembly or its
components separately" comparison (not built in this pass) -- the recurring
real case that motivated this: a store selling a whole bicycle assembly but
not its individual tire parts, or vice versa. Same shape and resumability
pattern as scripts/ingest_brickstore_minifig_inventories.py, gated by
brickstore_part_catalog.inventory_imported_at (separate from that table's
imported_at, same reasoning as the minifig table's gate).

Usage:
    DATABASE_URL=... python scripts/ingest_brickstore_assembly_inventories.py
    DATABASE_URL=... python scripts/ingest_brickstore_assembly_inventories.py --data-dir /path/to/extracted
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from _brickstore_release import ensure_latest, iter_assembly_inventory_files
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

INSERT_ITEMS_SQL = """
    INSERT INTO brickstore_part_assembly_inventory_items
        (parent_part_no, item_type, part_no, color_id, qty, is_extra, is_alternate, match_id, is_counterpart)
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

    cur.execute("SELECT part_no FROM brickstore_part_catalog WHERE inventory_imported_at IS NULL")
    pending = {r[0] for r in cur.fetchall()}
    print(f"{len(pending)} part(s) pending assembly-inventory import (most have no assembly file at all)")

    now = datetime.now(timezone.utc)
    processed = 0
    total_items = 0

    for part_no, items in iter_assembly_inventory_files(extract_dir):
        if part_no not in pending:
            continue

        if args.dry_run:
            print(f"    [dry-run] {part_no}: {len(items)} component(s)")
        else:
            if items:
                psycopg2.extras.execute_values(
                    cur, INSERT_ITEMS_SQL,
                    [(part_no, it["item_type"], it["part_no"], it["color_id"], it["qty"],
                      it["is_extra"], it["is_alternate"], it["match_id"], it["is_counterpart"])
                     for it in items],
                )
            cur.execute(
                "UPDATE brickstore_part_catalog SET inventory_imported_at = %s WHERE part_no = %s",
                (now, part_no),
            )
        processed += 1
        total_items += len(items)
        if processed % 1000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  ...{processed} processed", flush=True)

    # Every part without an assembly file is, definitionally, not an assembly --
    # mark the rest of `pending` done too so this doesn't rescan the whole
    # catalog every week looking for files that don't exist. Cheap stem-only
    # glob, not a second full parse of every assembly file.
    if not args.dry_run:
        existing_stems = {p.stem for p in (extract_dir / "P").glob("*.xml")}
        remaining = pending - existing_stems
        if remaining:
            psycopg2.extras.execute_values(
                cur,
                "UPDATE brickstore_part_catalog SET inventory_imported_at = data.imported_at "
                "FROM (VALUES %s) AS data (part_no, imported_at) WHERE brickstore_part_catalog.part_no = data.part_no",
                [(p, now) for p in remaining],
            )

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s. Assembly parts processed: {processed}, component rows: {total_items}")


if __name__ == "__main__":
    main()
