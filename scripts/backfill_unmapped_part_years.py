#!/usr/bin/env python3
"""Backfill year_released/last_used_year for bl_part_catalog PART rows that
backfill_last_used_year.py structurally can't reach: parts with zero
bricklink_mappings row at all, so there's no element_id to chain through to
a Rebrickable part_num.

Scope, confirmed live 2026-08-17: of the ~51,509 PART rows missing
last_used_year, 86% are printed/decorated variants, sticker sheets, or
non-LEGO-brand BrickLink categories (Minecraft/dinosaur "Brick Built"
items) -- not mold-succession candidates at all. Restricting to plain part
numbers (bare digits, optionally one trailing lowercase mold-variant letter,
e.g. "3684a") narrows this to the ~1,629 rows this script actually targets.

Rebrickable's own part_num can differ entirely from the BrickLink part_no
for the same physical part (confirmed empirically in
_rebrickable_lookup.py's docstring, e.g. Rebrickable "102220pr0001" ->
BrickLink "47205pb098") -- multipack pieces are one real example (BrickLink
"92355b" resolves to Rebrickable "94724", not "92355b"). So this uses
Rebrickable's undocumented but confirmed-working bricklink_id= filter
(same technique as _rebrickable_lookup.py's resolve_bl_part_no_reverse(),
inlined here to also pull year_from/year_to from the same response instead
of a second bulk call) rather than assuming the strings match.

One API call per part_no -- bricklink_id= is single-value only, no bulk
form exists (confirmed in _rebrickable_lookup.py). At ~1,629 parts and the
required >=1.2s/call pacing, a full run takes roughly 35-40 minutes.

This is a one-time gap-closing pass, not a recurring job -- the existing
backfill_last_used_year.py nightly timer already covers everything with a
real bricklink_mappings row going forward. Re-running this script is still
safe (upserts, and only selects rows still missing last_used_year), just
not scheduled.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/backfill_unmapped_part_years.py [--dry-run] [--limit N]
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
REBRICKABLE_API_BASE = "https://rebrickable.com/api/v3/lego"
INTER_CALL_DELAY = 1.2  # matches the pacing already established in _rebrickable_lookup.py callers
DEFAULT_RETRY_AFTER = 5.0

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

TARGET_SQL = """
    SELECT bpc.part_no
    FROM bl_part_catalog bpc
    WHERE bpc.item_type = 'PART' AND bpc.last_used_year IS NULL
      AND NOT EXISTS (SELECT 1 FROM bricklink_mappings bm WHERE bm.part_no = bpc.part_no)
      AND bpc.part_no ~ '^[0-9]+[a-z]?$'
    ORDER BY bpc.part_no
"""


def resolve_with_years(bl_part_no: str, max_retries: int = 3):
    """One call: bricklink_id= reverse lookup + inc_part_details=1 for years
    in the same response. Returns (rb_part_num, year_from, year_to) or
    (None, None, None) if Rebrickable has no record under any numbering."""
    url = f"{REBRICKABLE_API_BASE}/parts/"
    headers = {"Authorization": f"key {REBRICKABLE_API_KEY}", "User-Agent": "mocsource/1.0"}
    params = {"bricklink_id": bl_part_no, "inc_part_details": 1}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=25)
        except requests.exceptions.RequestException as e:
            print(f"  network error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_AFTER)
                continue
            return None, None, None
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else DEFAULT_RETRY_AFTER
            except ValueError:
                delay = DEFAULT_RETRY_AFTER
            print(f"  429 rate-limited (attempt {attempt + 1}/{max_retries}), Retry-After={delay}s", flush=True)
            time.sleep(delay)
            continue
        if 500 <= resp.status_code < 600:
            print(f"  {resp.status_code} server error (attempt {attempt + 1}/{max_retries})", flush=True)
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_AFTER)
                continue
            return None, None, None
        if resp.status_code != 200:
            print(f"  unexpected HTTP {resp.status_code} for {bl_part_no}", flush=True)
            return None, None, None
        results = resp.json().get("results", [])
        if not results:
            return None, None, None
        r = results[0]
        yf, yt = r.get("year_from"), r.get("year_to")
        # Rebrickable's sentinel for "matched, but no year data at all" is
        # 0, not null/absent -- confirmed live 2026-08-17 (BL "5483"/"31b").
        # Treat as no usable data, same as no match.
        if not yf:
            yf = None
        if not yt:
            yt = None
        return r.get("part_num"), yf, yt
    return None, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    parser.add_argument("--limit", type=int, default=None,
                         help="process only the first N target part_nos (for spot-checking)")
    args = parser.parse_args()

    if not REBRICKABLE_API_KEY:
        print("ERROR: REBRICKABLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(TARGET_SQL)
    part_nos = [r[0] for r in cur.fetchall()]
    if args.limit:
        part_nos = part_nos[:args.limit]
    print(f"{len(part_nos)} target part_no(s) to resolve "
          f"(~{len(part_nos) * INTER_CALL_DELAY / 60:.0f} min at {INTER_CALL_DELAY}s/call)")

    now = datetime.now(timezone.utc)
    resolved = no_year_data = no_match = 0
    for i, bl_part_no in enumerate(part_nos):
        rb_part_num, year_from, year_to = resolve_with_years(bl_part_no)
        time.sleep(INTER_CALL_DELAY)

        if rb_part_num is None:
            no_match += 1
            print(f"[{i + 1}/{len(part_nos)}] {bl_part_no}: no Rebrickable record", flush=True)
            continue
        if year_from is None and year_to is None:
            no_year_data += 1
            print(f"[{i + 1}/{len(part_nos)}] {bl_part_no}: matched rb={rb_part_num}, no usable year data", flush=True)
            continue

        resolved += 1
        if args.dry_run:
            print(f"[{i + 1}/{len(part_nos)}] [dry-run] {bl_part_no}: rb={rb_part_num} "
                  f"year_released={year_from} last_used_year={year_to}", flush=True)
        else:
            cur.execute(
                """
                UPDATE bl_part_catalog
                SET year_released = %s, last_used_year = %s, looked_up_at = %s
                WHERE part_no = %s
                """,
                (year_from, year_to, now, bl_part_no),
            )
            if (i + 1) % 200 == 0:
                conn.commit()
                print(f"[{i + 1}/{len(part_nos)}] committed", flush=True)

    if not args.dry_run:
        conn.commit()

    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone. Resolved: {resolved}, matched-but-no-year: {no_year_data}, "
          f"no Rebrickable record: {no_match}. Duration: {mins}m {secs}s")


if __name__ == "__main__":
    main()
