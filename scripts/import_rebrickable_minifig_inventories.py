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

RB_ROWS_SQL = """
    SELECT minifig_no, rb_part_num, rb_color_id, bl_color_id, quantity
    FROM rebrickable_minifig_inventory_items
    WHERE minifig_no = ANY(%s)
"""

BS_ROWS_SQL = """
    SELECT minifig_no, part_no, color_id, qty
    FROM brickstore_minifig_inventory_items
    WHERE minifig_no = ANY(%s) AND item_type = 'P' AND is_extra = false
"""


def load_color_map(conn) -> dict[int, int]:
    cur = conn.cursor()
    cur.execute("SELECT bl_id, rebrickable_id FROM colors WHERE rebrickable_id IS NOT NULL")
    result = {rb_id: bl_id for bl_id, rb_id in cur.fetchall()}
    cur.close()
    return result


def load_rb_to_bl_part_translation(conn, data_dir: Path) -> dict[tuple[str, int], str]:
    """{(rb_part_num, rb_color_id): bl_part_no}, bridged through element_id
    -- confirmed live 2026-07-23 that Rebrickable's elements.csv and this
    project's bricklink_mappings share the same element_id space (both
    resolve element_id 4190230 to the same physical part/color). Used ONLY
    for the conflict report below, never stored: rebrickable_minifig_
    inventory_items keeps rb_part_num untranslated by design (see this
    script's docstring) -- this translation is a read-only comparison aid,
    not a replacement for that stored column. Coverage is partial (not
    every element has a bricklink_mappings row), so a miss here means
    "untranslatable", not "confirmed absent" -- handled as its own bucket
    in the report rather than folded into rb_only."""
    element_map: dict[tuple[str, int], int] = {}  # (rb_part_num, rb_color_id) -> element_id
    with open(data_dir / "elements.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rb_color_id = int(row["color_id"])
                element_id = int(row["element_id"])
            except (ValueError, KeyError):
                continue
            element_map[(row["part_num"], rb_color_id)] = element_id

    cur = conn.cursor()
    cur.execute("SELECT element_id, part_no FROM bricklink_mappings")
    bl_by_element = dict(cur.fetchall())
    cur.close()

    translation: dict[tuple[str, int], str] = {}
    for key, element_id in element_map.items():
        bl_part_no = bl_by_element.get(element_id)
        if bl_part_no:
            translation[key] = bl_part_no
    return translation


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


def print_conflict_report(conn, data_dir: Path, minifig_nos: list[str]) -> None:
    """For minifigs present in both sources, diff (part, color, qty) using
    the rb_part_num -> bl_part_no translation (via elements.csv +
    bricklink_mappings, see load_rb_to_bl_part_translation) so the
    comparison is apples-to-apples rather than comparing two different
    numbering schemes directly. Rows whose part has no element_id mapping
    are bucketed separately as 'untranslatable' rather than counted as a
    conflict -- a miss there means "can't tell", not "confirmed absent".
    Report only -- resolving real discrepancies is a human judgment call."""
    if not minifig_nos:
        return
    translation = load_rb_to_bl_part_translation(conn, data_dir)

    cur = conn.cursor()
    cur.execute(RB_ROWS_SQL, (minifig_nos,))
    rb_rows = cur.fetchall()
    cur.execute(BS_ROWS_SQL, (minifig_nos,))
    bs_rows = cur.fetchall()
    cur.close()

    bs_by_minifig: dict[str, dict[tuple[str, int], int]] = defaultdict(dict)
    for minifig_no, part_no, color_id, qty in bs_rows:
        bs_by_minifig[minifig_no][(part_no, color_id)] = qty

    by_minifig: dict[str, dict] = defaultdict(
        lambda: {"matching": 0, "rb_only": [], "mismatched_qty": [], "untranslatable": []}
    )
    matched_bs_keys: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for minifig_no, rb_part, rb_color, bl_color, rb_qty in rb_rows:
        stats = by_minifig[minifig_no]
        # elements.csv (the translation source) is keyed by Rebrickable's OWN
        # color_id, so the lookup uses rb_color -- but brickstore_minifig_
        # inventory_items.color_id is BrickLink's numbering, so the actual
        # comparison against it must use bl_color (already translated at
        # import time via colors.rebrickable_id, same as the stored column).
        bl_part_no = translation.get((rb_part, rb_color))
        if bl_part_no is None or bl_color is None:
            stats["untranslatable"].append((rb_part, rb_color, rb_qty))
            continue
        bs_qty = bs_by_minifig.get(minifig_no, {}).get((bl_part_no, bl_color))
        if bs_qty is None:
            stats["rb_only"].append((rb_part, bl_part_no, bl_color, rb_qty))
        elif bs_qty != rb_qty:
            stats["mismatched_qty"].append((rb_part, bl_part_no, bl_color, rb_qty, bs_qty))
        else:
            stats["matching"] += 1
            matched_bs_keys[minifig_no].add((bl_part_no, bl_color))

    both_sources = {m for m in by_minifig if m in bs_by_minifig}
    with_any_conflict = {m: s for m in both_sources
                          if (s := by_minifig[m])["rb_only"] or s["mismatched_qty"]}
    print(f"\nConflict report: {len(both_sources)} minifig(s) present in both sources, "
          f"{len(with_any_conflict)} with at least one discrepancy (untranslatable parts excluded)")
    for minifig_no, s in list(with_any_conflict.items())[:20]:
        bs_only_count = len(bs_by_minifig[minifig_no]) - len(matched_bs_keys[minifig_no])
        print(f"  {minifig_no}: {s['matching']} matching, {len(s['rb_only'])} RB-only, "
              f"{len(s['mismatched_qty'])} qty-mismatched, {bs_only_count} BrickStore-only, "
              f"{len(s['untranslatable'])} untranslatable")
        for rb_part, bl_part, bl_color, rb_qty in s["rb_only"][:3]:
            print(f"      RB-only: part {rb_part} (bl:{bl_part}) color {bl_color} qty {rb_qty}")
        for rb_part, bl_part, bl_color, rb_qty, bs_qty in s["mismatched_qty"][:3]:
            print(f"      qty mismatch: part {rb_part} (bl:{bl_part}) color {bl_color}: RB={rb_qty} BrickStore={bs_qty}")
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
        print_conflict_report(conn, args.data_dir, imported_minifig_nos)

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
