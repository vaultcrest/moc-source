#!/usr/bin/env python3
"""Imports LEGO set part-inventories (part_num/color/qty per set) from
Rebrickable's bulk inventories.csv + inventory_parts.csv into
lego_set_inventory_items.

Found 2026-07-22: BrickStore's S/ bulk XML files (already used for minifig
inventories via ingest_brickstore_minifig_inventories.py) only cover 20,930
of our 27,318 known sets (76.6%) -- 10,153 sets had zero part-inventory data
anywhere in the DB. Rebrickable's own bulk data is the same origin as
lego_sets itself (populated by import_sets_csv.py from Rebrickable's own
sets.csv), and was verified live against 5 real sets (6980-1, 10030-1,
21030-1, 75192-1, 42056-1) to match Rebrickable's live
/lego/sets/{set_num}/parts/ API exactly -- same row counts, same individual
part/qty pairs -- so it should cover close to 100% of our set universe
instead of ~77%.

inventories.csv has one row per inventory *version* per set (some sets have
multiple versions -- later corrections). Only the MAX(version) per set_num
is used; inventory_parts.csv is filtered against that winning inventory_id.

rb_part_num stores Rebrickable's OWN part numbering, deliberately NOT
translated to a BrickLink part number -- see the migration's docstring
(alembic/versions/c2d3e4f5_lego_set_inventory_items.py) for why: there's no
existing direct Rebrickable-part_num -> BL-part_no lookup table, and
writing Rebrickable's numbering into anything resembling a BL-part_no
column is the exact mistake the 2026-07-14 bricklink_mappings corruption
bug taught this project to avoid. bl_color_id IS translated (via
colors.rebrickable_id), since colors are a small, already-well-mapped
dimension -- rows are kept even when the color can't be translated (left
NULL), since dropping them would make the inventory silently incomplete.

Resumable via lego_sets.inventory_imported_at (nullable gate, same pattern
as brickstore_minifig_catalog.inventory_imported_at) -- first run processes
every set with no inventory record yet, later runs only pick up sets added
by a subsequent sets.csv refresh (import_sets_csv.py).

Usage:
    DATABASE_URL=... python scripts/import_rebrickable_set_inventories.py [--data-dir PATH] [--dry-run]
    DATABASE_URL=... python scripts/import_rebrickable_set_inventories.py --set-num 6980-1 10030-1 [--dry-run]
"""
import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("REBRICKABLE_DATA_DIR", "/opt/mocsource/data/rebrickable"))

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

INSERT_SQL = """
    INSERT INTO lego_set_inventory_items
        (set_num, rb_part_num, rb_color_id, bl_color_id, quantity, is_spare, inventory_version)
    VALUES %s
    ON CONFLICT (set_num, rb_part_num, rb_color_id, is_spare) DO NOTHING
"""


def load_color_map(conn) -> dict[int, int]:
    """Return {rebrickable_id: bl_id} for colors with a known translation."""
    cur = conn.cursor()
    cur.execute("SELECT bl_id, rebrickable_id FROM colors WHERE rebrickable_id IS NOT NULL")
    result = {rb_id: bl_id for bl_id, rb_id in cur.fetchall()}
    cur.close()
    return result


def find_winning_inventories(data_dir: Path, pending: set[str]) -> tuple[dict[int, str], dict[int, int]]:
    """Stream inventories.csv, keep the MAX(version) inventory_id per
    pending set_num. Returns (inv_to_set, inv_to_version)."""
    best_version: dict[str, int] = {}
    best_inv_id: dict[str, int] = {}
    with open(data_dir / "inventories.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            set_num = row["set_num"]
            if set_num not in pending:
                continue
            try:
                inv_id = int(row["id"])
                version = int(row["version"])
            except (ValueError, KeyError):
                continue
            if version > best_version.get(set_num, -1):
                best_version[set_num] = version
                best_inv_id[set_num] = inv_id

    inv_to_set = {inv_id: set_num for set_num, inv_id in best_inv_id.items()}
    inv_to_version = {inv_id: best_version[set_num] for set_num, inv_id in best_inv_id.items()}
    return inv_to_set, inv_to_version


def stream_matching_rows(
    data_dir: Path, inv_to_set: dict[int, str], inv_to_version: dict[int, int], color_map: dict[int, int]
) -> dict[str, list[tuple]]:
    """Stream inventory_parts.csv, keep only rows whose inventory_id is a
    winning inventory. Returns {set_num: [(rb_part_num, rb_color_id,
    bl_color_id, quantity, is_spare, inventory_version), ...]}."""
    rows_by_set: dict[str, list[tuple]] = defaultdict(list)
    lines_read = 0
    with open(data_dir / "inventory_parts.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lines_read += 1
            if lines_read % 250_000 == 0:
                print(f"  ...{lines_read:,} inventory_parts.csv lines read", flush=True)
            try:
                inv_id = int(row["inventory_id"])
            except (ValueError, KeyError):
                continue
            set_num = inv_to_set.get(inv_id)
            if set_num is None:
                continue
            try:
                rb_part_num = row["part_num"].strip()
                rb_color_id = int(row["color_id"])
                quantity = int(row["quantity"])
            except (ValueError, KeyError):
                continue
            bl_color_id = color_map.get(rb_color_id)
            is_spare = row["is_spare"] == "True"
            rows_by_set[set_num].append(
                (rb_part_num, rb_color_id, bl_color_id, quantity, is_spare, inv_to_version[inv_id])
            )
    print(f"  {lines_read:,} inventory_parts.csv lines read total", flush=True)
    return rows_by_set


def dedupe_sum(raw_rows: list[tuple]) -> list[tuple]:
    """Fold duplicate (rb_part_num, rb_color_id, is_spare) rows by summing
    quantity -- bl_color_id/inventory_version taken from the first
    occurrence of each key (expected constant per key)."""
    folded: dict[tuple, list] = {}
    for rb_part_num, rb_color_id, bl_color_id, quantity, is_spare, version in raw_rows:
        key = (rb_part_num, rb_color_id, is_spare)
        if key not in folded:
            folded[key] = [rb_part_num, rb_color_id, bl_color_id, quantity, is_spare, version]
        else:
            folded[key][3] += quantity
    return [tuple(v) for v in folded.values()]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                         help=f"directory containing inventories.csv/inventory_parts.csv (default {DEFAULT_DATA_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    parser.add_argument("--set-num", nargs="+", default=None,
                         help="process exactly these set_nums, bypassing the resumable "
                                "inventory_imported_at gate")
    args = parser.parse_args()

    for fname in ("inventories.csv", "inventory_parts.csv"):
        if not (args.data_dir / fname).exists():
            print(f"ERROR: {args.data_dir / fname} not found -- run download_rebrickable_data.py first", file=sys.stderr)
            sys.exit(1)

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.set_num:
        pending = set(args.set_num)
        print(f"Processing {len(pending)} explicitly-specified set_num(s)")
    else:
        cur.execute("SELECT set_num FROM lego_sets WHERE inventory_imported_at IS NULL")
        pending = {r[0] for r in cur.fetchall()}
        print(f"{len(pending)} set(s) pending inventory import")

    if not pending:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    color_map = load_color_map(conn)
    print(f"{len(color_map)} Rebrickable colors have a known BrickLink translation")

    print("Scanning inventories.csv for winning (max-version) inventory per set...")
    inv_to_set, inv_to_version = find_winning_inventories(args.data_dir, pending)
    no_inventory = pending - set(inv_to_set.values())
    print(f"  {len(inv_to_set)} set(s) have a Rebrickable inventory record, "
          f"{len(no_inventory)} do not")

    print("Scanning inventory_parts.csv for matching rows...")
    rows_by_set = stream_matching_rows(args.data_dir, inv_to_set, inv_to_version, color_map)

    now = datetime.now(timezone.utc)
    processed = 0
    total_rows = 0
    total_inserted = 0

    for set_num in pending:
        raw_rows = rows_by_set.get(set_num, [])
        deduped = dedupe_sum(raw_rows)

        if args.dry_run:
            print(f"    [dry-run] {set_num}: {len(deduped)} row(s)")
        else:
            if deduped:
                # page_size must be >= len(deduped): execute_values() pages
                # internally (default page_size=100) by issuing multiple
                # separate INSERT statements, and cur.rowcount only reflects
                # the LAST one -- confirmed live 2026-07-22. Matches
                # import_rebrickable.py's existing page_size=BATCH pattern.
                # (rowcount can still legitimately be < len(deduped): that
                # just means some rows already existed from a prior run,
                # e.g. a --set-num reprocess -- not a bug, dedupe_sum's key
                # exactly matches the UNIQUE constraint so an in-batch
                # duplicate slipping through is structurally impossible.)
                psycopg2.extras.execute_values(
                    cur, INSERT_SQL,
                    [(set_num, *row) for row in deduped],
                    page_size=min(max(len(deduped), 1), 5000),
                )
                total_inserted += cur.rowcount
            cur.execute(
                "UPDATE lego_sets SET inventory_imported_at = %s WHERE set_num = %s",
                (now, set_num),
            )
        processed += 1
        total_rows += len(deduped)
        if processed % 1000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  ...{processed}/{len(pending)} sets processed", flush=True)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    insert_summary = (f"rows seen: {total_rows}" if args.dry_run else
                       f"rows seen: {total_rows}, new rows inserted: {total_inserted} "
                       f"({total_rows - total_inserted} already existed)")
    print(f"\nDone in {mins}m {secs}s. Sets processed: {processed} "
          f"({len(no_inventory)} with no Rebrickable inventory record), "
          f"{insert_summary}")


if __name__ == "__main__":
    main()
