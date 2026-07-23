#!/usr/bin/env python3
"""Imports minifig part-inventories (part_num/color/qty per minifig) from
Rebrickable's bulk inventories.csv + inventory_parts.csv into
rebrickable_minifig_inventory_items, using the fig_num <-> minifig_no
mapping built by map_rebrickable_minifigs.py. Then diffs the result against
brickstore_minifig_inventory_items (the existing BrickStore-sourced table)
for minifigs present in both, printing a conflict report.

Only minifigs with a row in minifig_mappings are candidates -- unmapped
minifigs are simply skipped (nothing to import them as). Mirrors
import_rebrickable_set_inventories.py's winning-max-version-per-inventory
streaming approach, but keyed by fig_num's OWN inventory (a minifig is a
first-class inventory owner in Rebrickable's model, not a set), then
written under minifig_no so the result lines up with
brickstore_minifig_inventory_items's identity space.

rb_part_num stores Rebrickable's own part numbering, deliberately NOT
translated to BrickLink -- same rationale as
import_rebrickable_set_inventories.py / lego_set_inventory_items. Confirmed
live 2026-07-23: no fig-prefixed (minifig) inventory row in
inventory_parts.csv has is_spare=True, so that column isn't carried here
(unlike lego_set_inventory_items, which does need it for real sets).

Resumable via brickstore_minifig_catalog.rb_inventory_imported_at (gate
distinct from that table's own inventory_imported_at, which tracks the
BrickStore-sourced import).

Usage:
    DATABASE_URL=... python scripts/import_rebrickable_minifig_inventories.py [--data-dir PATH] [--dry-run]
    DATABASE_URL=... python scripts/import_rebrickable_minifig_inventories.py --minifig-no hp637 [--dry-run]
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
    INSERT INTO rebrickable_minifig_inventory_items
        (minifig_no, rb_part_num, rb_color_id, bl_color_id, quantity, inventory_version)
    VALUES %s
    ON CONFLICT (minifig_no, rb_part_num, rb_color_id) DO NOTHING
"""

CONFLICT_CHECK_SQL = """
    SELECT rb.minifig_no, rb.rb_part_num, rb.bl_color_id, rb.quantity,
           bs.part_no, bs.color_id, bs.qty
    FROM rebrickable_minifig_inventory_items rb
    LEFT JOIN brickstore_minifig_inventory_items bs
      ON bs.minifig_no = rb.minifig_no
     AND bs.color_id = rb.bl_color_id
     AND bs.part_no = rb.rb_part_num
     AND bs.item_type = 'PART'
     AND bs.is_extra = false
    WHERE rb.minifig_no = ANY(%s)
"""


def load_color_map(conn) -> dict[int, int]:
    cur = conn.cursor()
    cur.execute("SELECT bl_id, rebrickable_id FROM colors WHERE rebrickable_id IS NOT NULL")
    result = {rb_id: bl_id for bl_id, rb_id in cur.fetchall()}
    cur.close()
    return result


def find_winning_minifig_inventories(data_dir: Path, pending_figs: set[str]) -> tuple[dict[int, str], dict[int, int]]:
    """Same max-version-per-owner logic as
    import_rebrickable_set_inventories.py, but the 'owner' here is a
    fig_num, not a set_num."""
    best_version: dict[str, int] = {}
    best_inv_id: dict[str, int] = {}
    with open(data_dir / "inventories.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fig_num = row["set_num"]
            if fig_num not in pending_figs:
                continue
            try:
                inv_id = int(row["id"])
                version = int(row["version"])
            except (ValueError, KeyError):
                continue
            if version > best_version.get(fig_num, -1):
                best_version[fig_num] = version
                best_inv_id[fig_num] = inv_id
    inv_to_fig = {inv_id: fig_num for fig_num, inv_id in best_inv_id.items()}
    inv_to_version = {inv_id: best_version[fig_num] for fig_num, inv_id in best_inv_id.items()}
    return inv_to_fig, inv_to_version


def stream_matching_rows(
    data_dir: Path, inv_to_fig: dict[int, str], inv_to_version: dict[int, int], color_map: dict[int, int]
) -> dict[str, list[tuple]]:
    rows_by_fig: dict[str, list[tuple]] = defaultdict(list)
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
            fig_num = inv_to_fig.get(inv_id)
            if fig_num is None:
                continue
            try:
                rb_part_num = row["part_num"].strip()
                rb_color_id = int(row["color_id"])
                quantity = int(row["quantity"])
            except (ValueError, KeyError):
                continue
            bl_color_id = color_map.get(rb_color_id)
            rows_by_fig[fig_num].append((rb_part_num, rb_color_id, bl_color_id, quantity, inv_to_version[inv_id]))
    print(f"  {lines_read:,} inventory_parts.csv lines read total", flush=True)
    return rows_by_fig


def dedupe_sum(raw_rows: list[tuple]) -> list[tuple]:
    """Fold duplicate (rb_part_num, rb_color_id) rows by summing quantity."""
    folded: dict[tuple, list] = {}
    for rb_part_num, rb_color_id, bl_color_id, quantity, version in raw_rows:
        key = (rb_part_num, rb_color_id)
        if key not in folded:
            folded[key] = [rb_part_num, rb_color_id, bl_color_id, quantity, version]
        else:
            folded[key][3] += quantity
    return [tuple(v) for v in folded.values()]


def print_conflict_report(conn, minifig_nos: list[str]) -> None:
    """For minifigs present in both sources, diff (part, color, qty).
    Report only -- resolving real discrepancies is a human judgment call."""
    if not minifig_nos:
        return
    cur = conn.cursor()
    cur.execute(CONFLICT_CHECK_SQL, (minifig_nos,))
    rows = cur.fetchall()
    cur.close()

    by_minifig: dict[str, dict] = defaultdict(lambda: {"both": 0, "rb_only": [], "mismatched_qty": []})
    for minifig_no, rb_part, rb_color, rb_qty, bs_part, bs_color, bs_qty in rows:
        stats = by_minifig[minifig_no]
        if bs_part is None:
            stats["rb_only"].append((rb_part, rb_color, rb_qty))
        elif bs_qty != rb_qty:
            stats["mismatched_qty"].append((rb_part, rb_color, rb_qty, bs_qty))
        else:
            stats["both"] += 1

    with_any_conflict = {m: s for m, s in by_minifig.items() if s["rb_only"] or s["mismatched_qty"]}
    print(f"\nConflict report: {len(by_minifig)} minifig(s) present in both sources, "
          f"{len(with_any_conflict)} with at least one discrepancy")
    for minifig_no, s in list(with_any_conflict.items())[:20]:
        print(f"  {minifig_no}: {s['both']} matching, {len(s['rb_only'])} RB-only, "
              f"{len(s['mismatched_qty'])} qty-mismatched")
        for rb_part, rb_color, rb_qty in s["rb_only"][:3]:
            print(f"      RB-only: part {rb_part} color {rb_color} qty {rb_qty}")
        for rb_part, rb_color, rb_qty, bs_qty in s["mismatched_qty"][:3]:
            print(f"      qty mismatch: part {rb_part} color {rb_color}: RB={rb_qty} BrickStore={bs_qty}")
    if len(with_any_conflict) > 20:
        print(f"  ... and {len(with_any_conflict) - 20} more")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                         help=f"directory containing inventories.csv/inventory_parts.csv (default {DEFAULT_DATA_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    parser.add_argument("--minifig-no", nargs="+", default=None,
                         help="process exactly these minifig_nos, bypassing the resumable "
                                "rb_inventory_imported_at gate")
    args = parser.parse_args()

    for fname in ("inventories.csv", "inventory_parts.csv"):
        if not (args.data_dir / fname).exists():
            print(f"ERROR: {args.data_dir / fname} not found -- run download_rebrickable_data.py first", file=sys.stderr)
            sys.exit(1)

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.minifig_no:
        cur.execute(
            "SELECT fig_num, minifig_no FROM minifig_mappings WHERE minifig_no = ANY(%s)",
            (args.minifig_no,),
        )
        mapping = {minifig_no: fig_num for fig_num, minifig_no in cur.fetchall()}
        unmapped = set(args.minifig_no) - set(mapping)
        if unmapped:
            print(f"  (skipping {sorted(unmapped)}: no minifig_mappings entry)")
        print(f"Processing {len(mapping)} explicitly-specified minifig_no(s)")
    else:
        cur.execute("""
            SELECT mm.fig_num, mm.minifig_no
            FROM minifig_mappings mm
            JOIN brickstore_minifig_catalog bmc ON bmc.minifig_no = mm.minifig_no
            WHERE bmc.rb_inventory_imported_at IS NULL
        """)
        mapping = {minifig_no: fig_num for fig_num, minifig_no in cur.fetchall()}
        print(f"{len(mapping)} mapped minifig(s) pending inventory import")

    if not mapping:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    color_map = load_color_map(conn)
    print(f"{len(color_map)} Rebrickable colors have a known BrickLink translation")

    pending_figs = set(mapping.values())
    print("Scanning inventories.csv for winning (max-version) inventory per minifig...")
    inv_to_fig, inv_to_version = find_winning_minifig_inventories(args.data_dir, pending_figs)
    no_inventory = pending_figs - set(inv_to_fig.values())
    print(f"  {len(inv_to_fig)} minifig(s) have a Rebrickable inventory record, "
          f"{len(no_inventory)} do not")

    print("Scanning inventory_parts.csv for matching rows...")
    rows_by_fig = stream_matching_rows(args.data_dir, inv_to_fig, inv_to_version, color_map)

    now = datetime.now(timezone.utc)
    processed = 0
    total_rows = 0
    total_inserted = 0
    imported_minifig_nos = []

    for minifig_no, fig_num in mapping.items():
        raw_rows = rows_by_fig.get(fig_num, [])
        deduped = dedupe_sum(raw_rows)

        if args.dry_run:
            print(f"    [dry-run] {minifig_no} ({fig_num}): {len(deduped)} row(s)")
        else:
            if deduped:
                psycopg2.extras.execute_values(
                    cur, INSERT_SQL,
                    [(minifig_no, *row) for row in deduped],
                    page_size=min(max(len(deduped), 1), 5000),
                )
                total_inserted += cur.rowcount
            cur.execute(
                "UPDATE brickstore_minifig_catalog SET rb_inventory_imported_at = %s WHERE minifig_no = %s",
                (now, minifig_no),
            )
            imported_minifig_nos.append(minifig_no)
        processed += 1
        total_rows += len(deduped)
        if processed % 1000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  ...{processed}/{len(mapping)} minifigs processed", flush=True)

    if not args.dry_run:
        conn.commit()

    if imported_minifig_nos:
        print_conflict_report(conn, imported_minifig_nos)

    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    insert_summary = (f"rows seen: {total_rows}" if args.dry_run else
                       f"rows seen: {total_rows}, new rows inserted: {total_inserted} "
                       f"({total_rows - total_inserted} already existed)")
    print(f"\nDone in {mins}m {secs}s. Minifigs processed: {processed} "
          f"({len(no_inventory)} with no Rebrickable inventory record), "
          f"{insert_summary}")


if __name__ == "__main__":
    main()
