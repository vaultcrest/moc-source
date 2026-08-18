#!/usr/bin/env python3
"""Ingests BrickLink's bulk Parts/Minifigure/Set catalog from the BrickStore
public release (see scripts/_brickstore_release.py) into
brickstore_part_catalog, brickstore_minifig_catalog, brickstore_set_catalog,
bl_part_catalog, brickstore_part_colors (per-part color availability, from
part_color_codes.xml), bricklink_alternates (alternate_no rows tagged
source='brickstore_alternate_ids'), and colors.bl_year_from/bl_year_to
(from colors.xml's own COLORYEARFROM/COLORYEARTO, added 2026-07-26 --
BrickLink's own year-introduced data, more authoritative than
colors.rebrickable_year_from, which disagreed with it for a third of
all colors).

Replaces scripts/scrape_bl_mold_data.py's live-API role for
name/item_type/category_id/alternate_no on bl_part_catalog -- all present in
this bulk download for the entire catalog at once, instead of trickling in
via ~42,000 individual paced BL API calls. Known gap: year_released isn't in
this download (the live scraper captured it only as a secondary mold-
succession tie-break signal, never the primary last_used_year signal, which
comes from Rebrickable) -- not populated here; existing values are left
untouched, not nulled out.

bricklink_alternates.source distinguishes this script's rows
('brickstore_alternate_ids', derived from each part's own ALTITEMIDS field)
from scripts/ingest_brickstore_mold_relationships.py's rows
('brickstore_mold_group', derived from BrickLink's separate "similar molds"
relationship pages) -- each script scopes its own delete+reinsert by
`source` so neither clobbers the other.

Usage:
    DATABASE_URL=... python scripts/ingest_brickstore_catalog.py [--dry-run]
    DATABASE_URL=... python scripts/ingest_brickstore_catalog.py --data-dir /path/to/extracted
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from _brickstore_release import (
    ensure_latest,
    iter_color_year_rows,
    iter_minifig_rows,
    iter_part_color_rows,
    iter_part_rows,
    iter_set_rows,
)
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

UPSERT_PART_CATALOG_SQL = """
    INSERT INTO brickstore_part_catalog (part_no, category_id, name, alternate_item_ids, imported_at)
    VALUES %s
    ON CONFLICT (part_no) DO UPDATE SET
        category_id = EXCLUDED.category_id,
        name = EXCLUDED.name,
        alternate_item_ids = EXCLUDED.alternate_item_ids,
        imported_at = EXCLUDED.imported_at
"""

UPSERT_BL_PART_CATALOG_SQL = """
    INSERT INTO bl_part_catalog (part_no, name, item_type, category_id, looked_up_at)
    VALUES %s
    ON CONFLICT (part_no) DO UPDATE SET
        name = EXCLUDED.name,
        item_type = EXCLUDED.item_type,
        category_id = EXCLUDED.category_id,
        looked_up_at = EXCLUDED.looked_up_at
"""

UPSERT_MINIFIG_CATALOG_SQL = """
    INSERT INTO brickstore_minifig_catalog (minifig_no, category_id, name, imported_at)
    VALUES %s
    ON CONFLICT (minifig_no) DO UPDATE SET
        category_id = EXCLUDED.category_id,
        name = EXCLUDED.name,
        imported_at = EXCLUDED.imported_at
"""

UPSERT_SET_CATALOG_SQL = """
    INSERT INTO brickstore_set_catalog (set_num, category_id, name, year, imported_at)
    VALUES %s
    ON CONFLICT (set_num) DO UPDATE SET
        category_id = EXCLUDED.category_id,
        name = EXCLUDED.name,
        year = EXCLUDED.year,
        imported_at = EXCLUDED.imported_at
"""

# colors rows are pre-seeded (seed_colors.py) -- UPDATE only, no insert case.
# bl_id here is BrickLink's own real numeric color id (colors.xml's <COLOR>),
# so a plain join is correct -- no name-matching needed, unlike part_color_codes.xml.
UPDATE_COLOR_YEARS_SQL = """
    UPDATE colors SET bl_year_from = %s, bl_year_to = %s WHERE bl_id = %s
"""


def ingest_parts(cur, extract_dir: Path, now: datetime, dry_run: bool) -> dict:
    part_rows = []
    bl_catalog_rows = []
    alternate_pairs = []

    for row in iter_part_rows(extract_dir):
        part_no = row["part_no"]
        if not part_no:
            continue
        category_id = int(row["category_id"]) if row["category_id"] else None
        part_rows.append((part_no, category_id, row["name"], row["alternate_item_ids"], now))
        bl_catalog_rows.append((part_no, row["name"], "PART", category_id, now))

        if row["alternate_item_ids"]:
            alts = {a.strip() for a in row["alternate_item_ids"].split(",") if a.strip() and a.strip() != part_no}
            for alt in alts:
                alternate_pairs.append((part_no, alt))

    if dry_run:
        print(f"    [dry-run] would upsert {len(part_rows)} brickstore_part_catalog rows, "
              f"{len(bl_catalog_rows)} bl_part_catalog rows, {len(alternate_pairs)} alternate pairs")
        return {"parts": len(part_rows), "alternates": len(alternate_pairs)}

    psycopg2.extras.execute_values(cur, UPSERT_PART_CATALOG_SQL, part_rows, page_size=1000)
    psycopg2.extras.execute_values(cur, UPSERT_BL_PART_CATALOG_SQL, bl_catalog_rows, page_size=1000)

    cur.execute("DELETE FROM bricklink_alternates WHERE source = 'brickstore_alternate_ids'")
    if alternate_pairs:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bricklink_alternates (part_no, alternate_no, source, updated_at)
            VALUES %s
            ON CONFLICT (part_no, alternate_no) DO UPDATE SET
                source = EXCLUDED.source,
                updated_at = EXCLUDED.updated_at
            """,
            [(p, a, "brickstore_alternate_ids", now) for p, a in alternate_pairs],
            page_size=1000,
        )

    return {"parts": len(part_rows), "alternates": len(alternate_pairs)}


def ingest_part_colors(cur, extract_dir: Path, now: datetime, dry_run: bool) -> dict:
    """Full truncate+reload each run -- single writer, no source tagging needed
    (unlike bricklink_alternates, which has multiple independent writers)."""
    color_rows = [(part_no, color_id, now) for part_no, color_id in iter_part_color_rows(extract_dir)]

    if dry_run:
        print(f"    [dry-run] would replace brickstore_part_colors with {len(color_rows)} rows")
        return {"part_colors": len(color_rows)}

    cur.execute("TRUNCATE TABLE brickstore_part_colors")
    if color_rows:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO brickstore_part_colors (part_no, color_id, imported_at) VALUES %s",
            color_rows,
            page_size=1000,
        )
    return {"part_colors": len(color_rows)}


def ingest_minifigs(cur, extract_dir: Path, now: datetime, dry_run: bool) -> dict:
    minifig_rows = []
    for row in iter_minifig_rows(extract_dir):
        category_id = int(row["category_id"]) if row["category_id"] else None
        minifig_rows.append((row["minifig_no"], category_id, row["name"], now))

    if dry_run:
        print(f"    [dry-run] would upsert {len(minifig_rows)} brickstore_minifig_catalog rows")
        return {"minifigs": len(minifig_rows)}

    psycopg2.extras.execute_values(cur, UPSERT_MINIFIG_CATALOG_SQL, minifig_rows, page_size=1000)
    return {"minifigs": len(minifig_rows)}


def ingest_sets(cur, extract_dir: Path, now: datetime, dry_run: bool) -> dict:
    set_rows = []
    for row in iter_set_rows(extract_dir):
        if not row["set_num"]:
            continue
        category_id = int(row["category_id"]) if row["category_id"] else None
        year = int(row["year"]) if row["year"] and row["year"].isdigit() else None
        set_rows.append((row["set_num"], category_id, row["name"], year, now))

    if dry_run:
        print(f"    [dry-run] would upsert {len(set_rows)} brickstore_set_catalog rows")
        return {"sets": len(set_rows)}

    psycopg2.extras.execute_values(cur, UPSERT_SET_CATALOG_SQL, set_rows, page_size=1000)
    return {"sets": len(set_rows)}


def ingest_color_years(cur, extract_dir: Path, dry_run: bool) -> dict:
    """UPDATE-only backfill of colors.bl_year_from/bl_year_to from colors.xml's
    own COLORYEARFROM/COLORYEARTO -- BrickLink's own year-introduced data,
    found 2026-07-26 to disagree with Rebrickable-derived rebrickable_year_from
    for 73 of 218 colors (by as much as 48 years). Never touches
    rebrickable_year_from/_to -- that column documents its own provenance."""
    rows = [(yf, yt, bl_id) for bl_id, yf, yt in iter_color_year_rows(extract_dir) if yf is not None]

    if dry_run:
        print(f"    [dry-run] would update bl_year_from/_to for {len(rows)} colors")
        return {"color_years": len(rows)}

    updated = 0
    for yf, yt, bl_id in rows:
        cur.execute(UPDATE_COLOR_YEARS_SQL, (yf, yt, bl_id))
        updated += cur.rowcount
    return {"color_years": updated}


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
    now = datetime.now(timezone.utc)

    part_stats = ingest_parts(cur, extract_dir, now, args.dry_run)
    color_stats = ingest_part_colors(cur, extract_dir, now, args.dry_run)
    minifig_stats = ingest_minifigs(cur, extract_dir, now, args.dry_run)
    set_stats = ingest_sets(cur, extract_dir, now, args.dry_run)
    color_year_stats = ingest_color_years(cur, extract_dir, args.dry_run)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s.")
    print(f"  Parts       : {part_stats['parts']}")
    print(f"  Alternates  : {part_stats['alternates']}")
    print(f"  Part colors : {color_stats['part_colors']}")
    print(f"  Minifigs    : {minifig_stats['minifigs']}")
    print(f"  Sets        : {set_stats['sets']}")
    print(f"  Color years : {color_year_stats['color_years']}")


if __name__ == "__main__":
    main()
