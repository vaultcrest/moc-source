#!/usr/bin/env python3
"""One-time/manual backfill of brickstore_minifig_catalog.year from
BrickLink's own catalog download, Minifigures.xml (ITEMYEAR field) -- a
manually-downloaded file (BrickLink's catalog download page requires an
authenticated account session, so unlike Rebrickable's CDN this isn't
automatable, same situation as codes.xml /
correct_bricklink_mappings_from_codes.py).

Found 2026-07-23: brickstore_minifig_catalog had no release-year column at
all. Minifigures.xml carries ITEMYEAR per minifig_no directly from
BrickLink, the same catalog that populates brickstore_minifig_catalog
itself (both ultimately mirror BrickLink's official item list), so this is
a same-source addition, not a cross-catalog translation.

Usage:
    DATABASE_URL=... python scripts/import_bricklink_minifig_years.py [--file PATH] [--dry-run]
"""
import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("BRICKLINK_CATALOG_DIR", "/opt/mocsource/data/bricklink_catalog"))

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

UPDATE_SQL = "UPDATE brickstore_minifig_catalog SET year = %s WHERE minifig_no = %s"


def load_years(path: Path) -> dict[str, int]:
    """{minifig_no: year} for ITEMTYPE=M entries with a parseable ITEMYEAR."""
    tree = ET.parse(path)
    root = tree.getroot()
    years: dict[str, int] = {}
    for item in root.findall("ITEM"):
        if item.findtext("ITEMTYPE") != "M":
            continue
        minifig_no = item.findtext("ITEMID")
        year_text = item.findtext("ITEMYEAR")
        if not minifig_no or not year_text:
            continue
        try:
            years[minifig_no] = int(year_text)
        except ValueError:
            continue
    return years


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_DATA_DIR / "Minifigures.xml",
                         help=f"path to Minifigures.xml (default {DEFAULT_DATA_DIR / 'Minifigures.xml'})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    print(f"Parsing {args.file}...")
    years = load_years(args.file)
    print(f"  {len(years)} minifig(s) have a year in the file")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT minifig_no, year FROM brickstore_minifig_catalog")
    current = dict(cur.fetchall())
    print(f"{len(current)} minifig(s) in brickstore_minifig_catalog")

    updated = 0
    already_set = 0
    unknown_minifig = 0
    changed_value = 0

    for minifig_no, year in years.items():
        if minifig_no not in current:
            unknown_minifig += 1
            continue
        existing = current[minifig_no]
        if existing == year:
            already_set += 1
            continue
        if existing is not None and existing != year:
            changed_value += 1

        if args.dry_run:
            if updated < 20:
                print(f"    [dry-run] {minifig_no}: {existing} -> {year}")
        else:
            cur.execute(UPDATE_SQL, (year, minifig_no))
        updated += 1
        if not args.dry_run and updated % 5000 == 0:
            conn.commit()
            print(f"  ...{updated} updated so far", flush=True)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    verb = "would be set" if args.dry_run else "set"
    print(f"\nDone in {mins}m {secs}s. {updated} year(s) {verb} "
          f"({changed_value} overwrote a differing existing value), "
          f"{already_set} already correct, {unknown_minifig} minifig_no(s) not in our catalog")


if __name__ == "__main__":
    main()
