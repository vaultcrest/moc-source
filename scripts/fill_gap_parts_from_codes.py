#!/usr/bin/env python3
"""Fills BL part_nos with ZERO bricklink_mappings row (the
reverse_map_bl_catalog.py backlog) using BrickLink's own codes.xml,
wherever codes.xml already has an element code for that part_no --
free, local, no BrickLink/Rebrickable API calls.

Found 2026-07-23: of the ~55K part_nos with no mapping at all, only
~5,100 (9%) have any codes.xml element code -- the other 91% are
structurally unreachable this way (BrickLink itself has never assigned
an element code to them; only reverse_map_bl_catalog.py's Rebrickable-
based discovery can find those). This script handles the reachable 9%
directly instead of waiting for the nightly Rebrickable-budget-limited
scan to eventually get to them.

correct_bricklink_mappings_from_codes.py already handles the case where
the blocking element_id already has a (wrong) bricklink_mappings row --
run that first. This script handles the other case: the element_id from
codes.xml has never been seen at all (no lego_elements row), which is a
genuine INSERT, not a correction -- same design_id-or-fallback pattern as
reverse_map_bl_catalog.py's resolve_one(), just design_id falls back to
the BL part_no (codes.xml has no design_id equivalent to offer).

A gap part_no with a codes.xml code that still can't be filled means the
blocking element_id already has a *verified* (source='bricklink') row
elsewhere -- a genuine BrickLink-vs-BrickLink-catalog-download disagreement,
left alone rather than overridden -- or its color has no bl_id in our
colors table at all (see COLOR_NAME_ALIASES in the correction script).

Usage:
    DATABASE_URL=... python scripts/fill_gap_parts_from_codes.py [--file PATH] [--dry-run]
"""
import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("BRICKLINK_CATALOG_DIR", "/opt/mocsource/data/bricklink_catalog"))

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

SOURCE_LABEL = "bricklink_codes_xml"

# Same naming variants as correct_bricklink_mappings_from_codes.py -- kept
# in sync manually, small enough not to warrant a shared module yet.
COLOR_NAME_ALIASES = {
    "(Not Applicable)": "None",
    "Glow In Dark Opaque": "Glow in Dark Opaque",
    "Royal Blue (Old Blue-Violet)": "Royal Blue(Old Blue-Violet)",
}

INSERT_ELEMENT_SQL = """
    INSERT INTO lego_elements (element_id, design_id)
    VALUES (%s, %s)
    ON CONFLICT (element_id) DO NOTHING
"""

INSERT_MAPPING_SQL = """
    INSERT INTO bricklink_mappings (element_id, part_no, color_id, source, updated_at)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (element_id) DO NOTHING
"""


def load_codes(path: Path) -> dict[str, tuple[str, str]]:
    """{element_id: (bl_part_no, color_name)}, ambiguous codes dropped --
    same logic as correct_bricklink_mappings_from_codes.py."""
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
                         help="print what would be inserted without touching the database")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    print(f"Parsing {args.file}...")
    codes = load_codes(args.file)
    print(f"  {len(codes)} unambiguous element codes loaded")

    # Group by target part_no so gap-check and reporting are per-part_no,
    # matching how reverse_map_bl_catalog.py's own backlog is counted.
    elements_by_part: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for element_id, (bl_part_no, color_name) in codes.items():
        elements_by_part[bl_part_no].append((element_id, color_name))

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    color_map = load_color_map(conn)
    print(f"{len(color_map)} BrickLink colors with a known name")

    cur.execute("""
        SELECT bpc.part_no FROM brickstore_part_catalog bpc
        WHERE NOT EXISTS (SELECT 1 FROM bricklink_mappings bm WHERE bm.part_no = bpc.part_no)
    """)
    gap_parts = {r[0] for r in cur.fetchall()}
    candidates = [p for p in gap_parts if p in elements_by_part]
    print(f"{len(gap_parts)} part_no(s) currently have zero bricklink_mappings row, "
          f"{len(candidates)} of those have a codes.xml element code")

    cur.execute("SELECT element_id FROM lego_elements")
    known_elements = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT element_id, part_no FROM bricklink_mappings")
    existing_mapping_owner = dict(cur.fetchall())

    now = datetime.now(timezone.utc)
    parts_filled = 0
    parts_still_blocked = 0
    elements_inserted = 0
    color_unmatched = 0
    already_mapped_elsewhere = 0
    examples = []

    for part_no in candidates:
        filled_this_part = False
        for element_id_str, color_name in elements_by_part[part_no]:
            element_id = int(element_id_str)
            bl_color_id = color_map.get(COLOR_NAME_ALIASES.get(color_name, color_name))
            if bl_color_id is None:
                color_unmatched += 1
                continue
            if element_id in known_elements:
                owner = existing_mapping_owner.get(element_id)
                # Already known and mapped elsewhere -- correct_bricklink_mappings_from_codes.py
                # owns fixing that case (it can tell if the owning row is
                # verified or not); this script only creates brand-new rows.
                if owner is not None:
                    already_mapped_elsewhere += 1
                    continue

            if args.dry_run:
                if elements_inserted < 20:
                    print(f"    [dry-run] element {element_id} -> {part_no}/{bl_color_id}")
            else:
                cur.execute(INSERT_ELEMENT_SQL, (element_id, part_no))
                cur.execute(INSERT_MAPPING_SQL, (element_id, part_no, bl_color_id, SOURCE_LABEL, now))
                if cur.rowcount == 0:
                    continue  # lost a race / already existed, shouldn't happen given known_elements check above
            elements_inserted += 1
            filled_this_part = True
            known_elements.add(element_id)
            if len(examples) < 10:
                examples.append((element_id, part_no, bl_color_id))

        if filled_this_part:
            parts_filled += 1
        else:
            parts_still_blocked += 1

        if not args.dry_run and parts_filled % 500 == 0 and parts_filled > 0:
            conn.commit()

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    verb = "would be filled" if args.dry_run else "filled"
    print(f"\nDone in {mins}m {secs}s. {len(candidates)} candidate part_no(s) checked: "
          f"{parts_filled} {verb} ({elements_inserted} element row(s) inserted), "
          f"{parts_still_blocked} still blocked "
          f"({already_mapped_elsewhere} by an already-mapped element, {color_unmatched} by an unmatched color)")
    print("Sample fills:")
    for e in examples:
        print(" ", e)


if __name__ == "__main__":
    main()
