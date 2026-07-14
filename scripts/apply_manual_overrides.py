#!/usr/bin/env python3
"""Apply hand-verified corrections/N-A markers from cache/manual_overrides.yaml
to bricklink_mappings, for rows scripts/fix_rebrickable_part_nos.py couldn't
resolve automatically (tracked as `unresolved` in rebrickable_part_no_fixes
after exhausting both its bulk and element-id fallback tiers).

manual_overrides.yaml is keyed by element_id (string). Two entry shapes:

  A correction -- a real BrickLink part number, verified by hand:
    '6668520':
      bl_part_no: 100588pb01
      note: "verified directly on BrickLink catalog"

  Confirmed no BrickLink equivalent exists (Rebrickable tracks detail
  BrickLink doesn't -- not an error, not "unresolved", just genuinely N/A).
  bl_part_no accepts null, "", or the literal "N/A" (case-insensitive) --
  whichever's easiest to type:
    '6294039':
      bl_part_no: N/A
      note: "Duplo part, no BrickLink catalog equivalent exists"

Corrections update bricklink_mappings.part_no for that element_id (source
set to 'manual'), and -- once no other bricklink_mappings row still
references the old part_no -- clean up its now-orphaned bl_part_catalog /
bricklink_alternates rows and mark rebrickable_part_no_fixes so the
automated correction script stops retrying it (method='manual').

N/A entries NULL OUT bricklink_mappings.part_no (source='manual_na') --
the original Rebrickable value isn't a real BrickLink number and shouldn't
be used for our purposes, so nothing downstream should be able to mistake
it for one. The original value isn't lost, though: it's preserved as
old_part_no in rebrickable_part_no_fixes (method='manual_na') before being
cleared, same durable tracking rebrickable_part_no_fixes already provides
for every other row. No changes needed to fix_rebrickable_part_nos.py's
retry query -- a NULL part_no never matches its `~ 'pr[0-9]+$'` filter, so
N/A rows drop out of the automated queue for free. Won't get silently
re-populated by a future scrape/import either -- both import_rebrickable.py
(ON CONFLICT DO NOTHING) and scrape_pab.py's enrich_new_elements() only
ever touch element_ids that don't already have a bricklink_mappings row.

Idempotent -- safe to re-run the whole file any time.

Usage:
    DATABASE_URL=... python scripts/apply_manual_overrides.py [--file cache/manual_overrides.yaml] [--dry-run]
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import yaml
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OVERRIDES_FILE = Path(__file__).resolve().parent.parent / "cache" / "manual_overrides.yaml"

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

UPSERT_FIX_SQL = """
    INSERT INTO rebrickable_part_no_fixes (old_part_no, new_part_no, method, attempted_at)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (old_part_no) DO UPDATE SET
        new_part_no = EXCLUDED.new_part_no,
        method = EXCLUDED.method,
        attempted_at = EXCLUDED.attempted_at
"""


def lookup_element(cur, element_id: int) -> tuple[bool, str | None]:
    """Returns (exists, part_no). part_no may legitimately be None for an
    element already marked N/A by a previous run -- that's distinct from the
    element not existing in bricklink_mappings at all."""
    cur.execute("SELECT part_no FROM bricklink_mappings WHERE element_id = %s", (element_id,))
    row = cur.fetchone()
    if row is None:
        return False, None
    return True, row[0]


def apply_correction(cur, element_id: int, old_part_no: str | None, new_part_no: str, now, dry_run: bool) -> None:
    if dry_run:
        return
    cur.execute(
        "UPDATE bricklink_mappings SET part_no = %s, source = 'manual' WHERE element_id = %s",
        (new_part_no, element_id),
    )
    # old_part_no is None if this element was previously marked N/A (part_no
    # already NULL) -- nothing to clean up or track for a value that never
    # existed, and old_part_no can't be a NULL primary key in the fixes table.
    if old_part_no is not None:
        cur.execute("SELECT count(*) FROM bricklink_mappings WHERE part_no = %s", (old_part_no,))
        still_referenced = cur.fetchone()[0] > 0
        if not still_referenced:
            cur.execute("DELETE FROM bl_part_catalog WHERE part_no = %s", (old_part_no,))
            cur.execute("DELETE FROM bricklink_alternates WHERE part_no = %s", (old_part_no,))
            cur.execute(UPSERT_FIX_SQL, (old_part_no, new_part_no, "manual", now))
    cur.connection.commit()


def apply_na(cur, element_id: int, old_part_no: str | None, now, dry_run: bool) -> None:
    if dry_run:
        return
    cur.execute(
        "UPDATE bricklink_mappings SET part_no = NULL, source = 'manual_na' WHERE element_id = %s",
        (element_id,),
    )
    # Already NULL (re-running against an element already marked N/A) --
    # nothing new to track, and old_part_no can't be a NULL primary key.
    if old_part_no is not None:
        cur.execute(UPSERT_FIX_SQL, (old_part_no, None, "manual_na", now))
    cur.connection.commit()


def is_na_sentinel(bl_part_no) -> bool:
    """True for null, empty string, or the literal "N/A" (any case) -- all
    equally valid ways to write "confirmed no BrickLink equivalent"."""
    if bl_part_no is None:
        return True
    if isinstance(bl_part_no, str) and bl_part_no.strip().lower() in ("", "n/a"):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_OVERRIDES_FILE,
                         help=f"path to manual_overrides.yaml (default {DEFAULT_OVERRIDES_FILE})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        overrides = yaml.safe_load(f) or {}

    if not overrides:
        print("No entries in manual_overrides.yaml. Nothing to do.")
        return

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    corrected = marked_na = skipped = 0

    for element_id_str, entry in overrides.items():
        element_id = int(element_id_str)
        exists, old_part_no = lookup_element(cur, element_id)
        if not exists:
            print(f"  element_id {element_id}: not found in bricklink_mappings, skipping", flush=True)
            skipped += 1
            continue

        new_part_no = entry.get("bl_part_no")
        note = entry.get("note", "")

        if is_na_sentinel(new_part_no):
            print(f"  element_id {element_id}: {old_part_no} -> N/A (clearing part_no)  ({note})", flush=True)
            apply_na(cur, element_id, old_part_no, now, args.dry_run)
            marked_na += 1
        else:
            print(f"  element_id {element_id}: {old_part_no} -> {new_part_no}  ({note})", flush=True)
            apply_correction(cur, element_id, old_part_no, new_part_no, now, args.dry_run)
            corrected += 1

    cur.close()
    conn.close()

    print(f"\nDone. Corrected: {corrected}, marked N/A: {marked_na}, skipped: {skipped}.")
    if args.dry_run:
        print("(dry-run -- nothing was written)")


if __name__ == "__main__":
    main()
