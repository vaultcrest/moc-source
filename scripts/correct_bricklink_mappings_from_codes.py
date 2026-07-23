#!/usr/bin/env python3
"""One-time correction pass for bricklink_mappings using BrickLink's own
official element-code catalog download (codes.xml), a manually-downloaded
file (BrickLink's catalog download page requires an authenticated account
session -- there's no unauthenticated CDN like Rebrickable's, so this isn't
automatable the way download_rebrickable_data.py is).

Found 2026-07-23: of the 89,343 bricklink_mappings rows not already sourced
directly from a live BrickLink API call (source != 'bricklink' -- mostly
Rebrickable-derived, many predating the 2026-07-14 corruption bug fixes),
codes.xml disagrees with 8,754 of them. Spot-checked live: element_id
4109767 was stored as part_no 80039 (which has no name in bl_part_catalog
at all -- looks bogus) while codes.xml says the real answer is 14pb10
("Road Sign Round with No Left Turn Pattern," a real named part). A second
sample (element 6535524) already agreed exactly with a prior
source='bricklink' correction, confirming codes.xml is trustworthy ground
truth, not just a second guess.

bricklink_mappings.element_id is the PK (FK'd from lego_elements), and
every lego_elements row already has exactly one bricklink_mappings row
(confirmed live: zero elements have no row at all) -- so there is no
separate "insert new mapping" case here, only "correct an existing wrong
one." Some of those corrections land on part_nos that currently have ZERO
bricklink_mappings rows pointing to them at all (the reverse_map_bl_catalog.py
gap) -- filling those gaps is a side effect of the same UPDATE, not a
distinct code path.

codes.xml's <COLOR> is a color NAME (e.g. "White"), translated via
colors.bl_name -> bl_id -- BrickLink's own naming, so this is a direct
same-source lookup, not a cross-catalog translation like the Rebrickable
color_id bridge used elsewhere. Element codes that appear more than once
in codes.xml with conflicting (part_no, color) are skipped entirely rather
than guessed at (716 such conflicts found in the full file).

Usage:
    DATABASE_URL=... python scripts/correct_bricklink_mappings_from_codes.py [--file PATH] [--dry-run]
"""
import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("BRICKLINK_CATALOG_DIR", "/opt/mocsource/data/bricklink_catalog"))

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

SOURCE_LABEL = "bricklink_codes_xml"

UPDATE_SQL = """
    UPDATE bricklink_mappings
    SET part_no = %s, color_id = %s, item_type = 'PART', source = %s, updated_at = %s
    WHERE element_id = %s
"""


def load_codes(path: Path) -> dict[str, tuple[str, str]]:
    """{element_id: (bl_part_no, color_name)} for ITEMTYPE=P entries.
    Element codes with conflicting duplicate entries are dropped entirely
    -- ambiguous ground truth is worse than none, never guessed at."""
    tree = ET.parse(path)
    root = tree.getroot()
    codes: dict[str, tuple[str, str]] = {}
    conflicted: set[str] = set()
    for item in root.findall("ITEM"):
        if item.findtext("ITEMTYPE") != "P":
            continue
        element_id = item.findtext("CODENAME")
        part_no = item.findtext("ITEMID")
        color = item.findtext("COLOR")
        if not element_id or not part_no:
            continue
        key = (part_no, color)
        if element_id in codes and codes[element_id] != key:
            conflicted.add(element_id)
            continue
        codes[element_id] = key
    for element_id in conflicted:
        codes.pop(element_id, None)
    return codes


# codes.xml's <COLOR> text doesn't always match colors.bl_name verbatim --
# found live 2026-07-23 checking all 173 distinct codes.xml color strings
# against colors.bl_name: 3 are pure naming variants (case/spacing/label),
# not missing data, applied before the color_map lookup. The other 2
# mismatches ("Pearl Dark Gray", "Rose Pink") have no equivalent bl_id in
# our colors table at all -- a real gap in that table, not a naming issue,
# left unmatched rather than guessed at.
COLOR_NAME_ALIASES = {
    "(Not Applicable)": "None",
    "Glow In Dark Opaque": "Glow in Dark Opaque",
    "Royal Blue (Old Blue-Violet)": "Royal Blue(Old Blue-Violet)",
}


def load_color_map(conn) -> dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT bl_name, bl_id FROM colors WHERE bl_name IS NOT NULL")
    result = dict(cur.fetchall())
    cur.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_DATA_DIR / "codes.xml",
                         help=f"path to codes.xml (default {DEFAULT_DATA_DIR / 'codes.xml'})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be corrected without touching the database")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    print(f"Parsing {args.file}...")
    codes = load_codes(args.file)
    print(f"  {len(codes)} unambiguous element codes loaded")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    color_map = load_color_map(conn)
    print(f"{len(color_map)} BrickLink colors with a known name")

    cur.execute("SELECT element_id, part_no, color_id FROM bricklink_mappings WHERE source != 'bricklink'")
    rows = cur.fetchall()
    print(f"{len(rows)} unverified bricklink_mappings row(s) to check")

    now = datetime.now(timezone.utc)
    corrected = 0
    already_agreed = 0
    no_code = 0
    color_unmatched = 0
    examples = []

    for element_id, part_no, color_id in rows:
        code = codes.get(str(element_id))
        if code is None:
            no_code += 1
            continue
        bl_part_no, color_name = code
        bl_color_id = color_map.get(COLOR_NAME_ALIASES.get(color_name, color_name))
        if bl_color_id is None:
            color_unmatched += 1
            continue
        if bl_part_no == part_no and bl_color_id == color_id:
            already_agreed += 1
            continue

        if args.dry_run:
            if corrected < 20:
                print(f"    [dry-run] element {element_id}: ({part_no}, {color_id}) -> ({bl_part_no}, {bl_color_id})")
        else:
            cur.execute(UPDATE_SQL, (bl_part_no, bl_color_id, SOURCE_LABEL, now, element_id))
        corrected += 1
        if len(examples) < 5:
            examples.append((element_id, part_no, color_id, bl_part_no, bl_color_id))

        if not args.dry_run and corrected % 2000 == 0:
            conn.commit()
            print(f"  ...{corrected} corrected so far", flush=True)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    verb = "would be corrected" if args.dry_run else "corrected"
    print(f"\nDone in {mins}m {secs}s. {len(rows)} row(s) checked: "
          f"{corrected} {verb}, {already_agreed} already agreed, "
          f"{no_code} had no matching code, {color_unmatched} had an unmatched color name")
    print("Sample corrections:")
    for e in examples:
        print(" ", e)


if __name__ == "__main__":
    main()
