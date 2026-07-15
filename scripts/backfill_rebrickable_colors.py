#!/usr/bin/env python3
"""Backfill colors.rebrickable_id and rebrickable_year_from/_to.

rebrickable_id: matches Rebrickable colors to existing colors rows by bl_id,
using each Rebrickable color's external_ids.BrickLink.ext_ids list (a
Rebrickable color can list multiple BrickLink ids). This is the same lookup
already built (and proven live) in mocsource/rebrickable_client.py's
_fetch_color_map_sync, run here as a one-time/occasional standalone backfill
rather than inside the (currently disabled) per-request enrichment path.

rebrickable_year_from/_to: Rebrickable's first/last observed usage year for
that color across any part. NOT available from the live REST API (confirmed
2026-07-14 by dumping the full JSON of both /lego/colors/ and
/lego/colors/{id}/ -- neither has a year field anywhere). Only available via
Rebrickable's bulk colors.csv download product
(https://cdn.rebrickable.com/media/downloads/colors.csv.gz, confirmed live,
unauthenticated). Fetched fresh each run rather than cached locally like
backfill_last_used_year.py's elements.csv -- that convention exists because
elements.csv is huge; this file is ~275 rows, trivial to re-download, and a
live fetch avoids a stale y2 (which drifts forward as new sets ship).

Additive only: writes rebrickable_id/rebrickable_year_from/rebrickable_year_to
and nothing else. bl_id, bl_name, lego_id, lego_name, hex are never read for
matching purposes beyond bl_id/bl_name (for reporting) and are never written.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/backfill_rebrickable_colors.py [--dry-run]
"""
import argparse
import csv
import gzip
import io
import os
import sys

import psycopg2
import requests
from dotenv import load_dotenv

from _rebrickable_lookup import _get_with_retry

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
REBRICKABLE_COLORS_URL = "https://rebrickable.com/api/v3/lego/colors/"
REBRICKABLE_COLORS_CSV_URL = "https://cdn.rebrickable.com/media/downloads/colors.csv.gz"

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def fetch_rb_colors(api_key: str) -> list[dict]:
    """Fetch all Rebrickable colors, following pagination just in case the
    ~200-color list ever exceeds one page."""
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    results: list[dict] = []
    url, params = REBRICKABLE_COLORS_URL, {"page_size": 300}
    while url:
        resp = _get_with_retry(url, params, headers)
        if resp is None or resp.status_code != 200:
            print(f"ERROR: Rebrickable colors fetch failed "
                  f"(status {resp.status_code if resp else 'no response'})", file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        results.extend(data.get("results", []))
        url, params = data.get("next"), None  # 'next' is a full URL carrying its own query params
    return results


def build_bl_to_rb_map(rb_colors: list[dict]) -> dict[int, int]:
    """Return {bl_id: rebrickable_id}."""
    mapping: dict[int, int] = {}
    for color in rb_colors:
        rb_id = color["id"]
        bl_ids = color.get("external_ids", {}).get("BrickLink", {}).get("ext_ids", [])
        for bl_id in bl_ids:
            mapping[int(bl_id)] = rb_id
    return mapping


def fetch_rb_color_years() -> dict[int, tuple[int | None, int | None]]:
    """Return {rebrickable_id: (year_from, year_to)} from Rebrickable's bulk
    colors.csv download (y1/y2 columns) -- the only source for this data,
    see module docstring. Unauthenticated, no API key needed."""
    resp = requests.get(REBRICKABLE_COLORS_CSV_URL, timeout=30)
    if resp.status_code != 200:
        print(f"WARNING: Rebrickable colors.csv fetch failed (status {resp.status_code}), "
              f"skipping year backfill", file=sys.stderr)
        return {}
    raw = gzip.decompress(resp.content)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    years: dict[int, tuple[int | None, int | None]] = {}
    for row in reader:
        try:
            rb_id = int(row["id"])
        except (KeyError, ValueError):
            continue
        y1 = int(row["y1"]) if row.get("y1") else None
        y2 = int(row["y2"]) if row.get("y2") else None
        years[rb_id] = (y1, y2)
    return years


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    if not REBRICKABLE_API_KEY:
        print("ERROR: REBRICKABLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print("Fetching Rebrickable colors...")
    rb_colors = fetch_rb_colors(REBRICKABLE_API_KEY)
    print(f"  {len(rb_colors)} Rebrickable colors fetched")

    bl_to_rb = build_bl_to_rb_map(rb_colors)
    print(f"  {len(bl_to_rb)} distinct BrickLink id(s) mapped via external_ids.BrickLink")

    print("Fetching Rebrickable colors.csv for year data...")
    rb_years = fetch_rb_color_years()
    print(f"  {len(rb_years)} Rebrickable color year entries fetched")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT bl_id, bl_name, rebrickable_id FROM colors ORDER BY bl_id")
    rows = cur.fetchall()

    matched = year_matched = 0
    unmatched_rows: list[tuple[int, str]] = []
    year_unmatched_rows: list[tuple[int, str, int]] = []
    for bl_id, bl_name, existing_rb_id in rows:
        rb_id = bl_to_rb.get(bl_id, existing_rb_id)
        if rb_id is None:
            unmatched_rows.append((bl_id, bl_name))
            continue
        matched += 1
        if args.dry_run:
            print(f"    [dry-run] bl_id={bl_id} ({bl_name}) -> rebrickable_id={rb_id}")
        else:
            cur.execute(
                "UPDATE colors SET rebrickable_id = %s WHERE bl_id = %s",
                (rb_id, bl_id),
            )

        years = rb_years.get(rb_id)
        if years is None:
            year_unmatched_rows.append((bl_id, bl_name, rb_id))
            continue
        y1, y2 = years
        year_matched += 1
        if args.dry_run:
            print(f"    [dry-run] bl_id={bl_id} ({bl_name}) -> years {y1}-{y2}")
        else:
            cur.execute(
                "UPDATE colors SET rebrickable_year_from = %s, rebrickable_year_to = %s WHERE bl_id = %s",
                (y1, y2, bl_id),
            )

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone. {matched}/{len(rows)} colors matched to a rebrickable_id, {len(unmatched_rows)} unmatched.")
    print(f"      {year_matched}/{matched} of those also got year data, "
          f"{len(year_unmatched_rows)} had a rebrickable_id but no year entry in colors.csv.")
    if unmatched_rows:
        print("Unmatched bl_id rows (no external_ids.BrickLink entry from Rebrickable):")
        for bl_id, bl_name in unmatched_rows:
            print(f"  bl_id={bl_id}  bl_name={bl_name}")
    if year_unmatched_rows:
        print("Rows with a rebrickable_id but no colors.csv year entry:")
        for bl_id, bl_name, rb_id in year_unmatched_rows:
            print(f"  bl_id={bl_id}  bl_name={bl_name}  rebrickable_id={rb_id}")


if __name__ == "__main__":
    main()
