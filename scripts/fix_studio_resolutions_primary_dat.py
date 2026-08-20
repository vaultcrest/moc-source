#!/usr/bin/env python3
"""One-time correction pass for studio_resolutions.part_file, 2026-08-19.

studio_resolutions was originally seeded (scripts/seed.py) from
brick_palettes_generator's canonical_mapping.json, which in turn read a
stale, wrong cache/studio_part_definitions.json (fixed separately in that
project via build_studio_definition_index.py -- see that script's
docstring for the full root-cause writeup). 164 parts inherited a wrong
part_file this way -- e.g. "3010" (Brick 1 x 4) stored as "301021.dat"
(a LEGO element/design-ID-looking auxiliary filename) instead of the real
"3010.dat". Found by comparing our generated palettes against real
BrickLink-distributed reference palette files (BDP Series 8-11).

Re-derives the correct filename directly from
brick_palettes_generator/data/studio_files/StudioPartDefinition2.txt
using the primary-row selection rule: isPerfectForCulling == "o" AND
BLCatalogIndex != "0" AND LDraw ItemNo is non-empty and doesn't start
with "bl_". No persistent copy of the .txt file's data is kept in this
DB -- parsed fresh each run, matching the ad hoc reconciliation approach
already used elsewhere this session.

Fixed 2026-08-20: the original rule additionally required
IsDecorated == "False" (exact, case-sensitive string match), found wrong
two ways while investigating 8 real palette mismatches surfaced by a
manual Stud.io load-and-render check (`output/studio_palettes/Mismatch
Review OURS`/`REF`): (1) the source file's casing is inconsistent for
this field (True/False/true/false/TRUE/FALSE all appear for real primary
rows), so even non-decorated primary rows sometimes failed the exact
"False" check; (2) decorated parts (e.g. printed minifig heads) have
their own legitimate primary rows too, just with IsDecorated=True --
excluding them entirely was wrong, not just case-sensitive. Verified live
against the full file: dropping the check resolves all 7 of the 8
mismatches that had a real primary row available, with zero new
ambiguous BL-ItemNo collisions introduced. The 8th (`3468c01`, an
IsAssembly?=true sub-component row) has no correct answer anywhere in
this file at all -- its part_file was fixed separately as a one-off
manual UPDATE (source_type='manual_studio_render_verified'), sourced
from Sean's direct Stud.io render test rather than derived here.

Only touches resolved=true rows where the derived primary filename
differs from what's stored; source_type is set to
'studio_definition_primary' so this correction pass is traceable and
distinguishable from the inherited (wrong) 'studio_definition_ldraw'/
'studio_definition_missing' tags.

Not a recurring job -- run manually whenever Sean reloads
StudioPartDefinition2.txt from a real Stud.io install and wants
studio_resolutions re-checked against it.

Usage:
    DATABASE_URL=... python scripts/fix_studio_resolutions_primary_dat.py [--dry-run]
"""
import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

DEFAULT_DEFINITION_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "brick_palettes_generator" / "data" / "studio_files" / "StudioPartDefinition2.txt"
)

UPDATE_SQL = """
    UPDATE studio_resolutions
    SET part_file = %s, source_type = 'studio_definition_primary'
    WHERE part_no = %s
"""


def build_primary_index(definition_file: Path) -> dict:
    index = {}
    ambiguous = set()
    with open(definition_file, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {h: i for i, h in enumerate(header)}
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < len(header):
                continue
            bl_no = cols[idx["BL ItemNo"]]
            if not bl_no:
                continue
            ldraw = cols[idx["LDraw ItemNo"]]
            is_culling = cols[idx["isPerfectForCulling"]]
            bl_cat_idx = cols[idx["BLCatalogIndex"]]
            if (is_culling == "o" and bl_cat_idx != "0"
                    and ldraw and not ldraw.startswith("bl_")):
                if bl_no in index and index[bl_no] != ldraw:
                    ambiguous.add(bl_no)
                    continue  # multiple disagreeing primary rows -- skip, don't guess
                index[bl_no] = ldraw
    if ambiguous:
        print(f"  {len(ambiguous)} BL ItemNo(s) had >1 disagreeing primary row, skipped: {sorted(ambiguous)[:10]}{'...' if len(ambiguous) > 10 else ''}")
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--definition-file", type=Path, default=DEFAULT_DEFINITION_FILE)
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be corrected without touching the database")
    args = parser.parse_args()

    print(f"Parsing {args.definition_file}...")
    primary = build_primary_index(args.definition_file)
    print(f"Built primary mapping for {len(primary)} BL ItemNos")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT part_no, part_file, source_type FROM studio_resolutions WHERE resolved = true")
    rows = cur.fetchall()

    corrections = []
    for part_no, stored_file, source_type in rows:
        correct = primary.get(part_no)
        if correct and correct != stored_file:
            corrections.append((part_no, stored_file, correct, source_type))

    print(f"\n{len(corrections)} correction(s) found (of {len(rows)} resolved rows checked)")
    for part_no, old, new, old_source in corrections:
        print(f"  {part_no}: {old} -> {new} (was source_type={old_source})")

    if args.dry_run:
        print("\n[dry-run] no changes written")
        cur.close()
        conn.close()
        return

    for part_no, old, new, old_source in corrections:
        cur.execute(UPDATE_SQL, (new, part_no))
    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. Corrected {len(corrections)} row(s).")


if __name__ == "__main__":
    main()
