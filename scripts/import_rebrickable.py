#!/usr/bin/env python3
"""Import Rebrickable parts + elements into lego_elements and bricklink_mappings.

Reads parts.csv and elements.csv from the rebrickable data directory and
inserts new entries with ON CONFLICT DO NOTHING so existing PAB/canonical
data is never overwritten.

Color mapping: Rebrickable color IDs are matched to BrickLink color IDs by
name (case-insensitive). Elements whose color cannot be mapped are skipped.

Part number: elements.csv's part_num is Rebrickable's OWN numbering (e.g.
"27372pr0006"), not a BrickLink part number -- it must never be written into
bricklink_mappings.part_no directly (that was the root cause behind 29,689
untranslated rows found 2026-07-14). This script resolves the real BrickLink
part number for every distinct part_num via Rebrickable's bulk parts API
(scripts/_rebrickable_lookup.py) before inserting; part_nums that don't
translate are skipped, not written with a guessed/raw value.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/import_rebrickable.py [rebrickable_dir]

Default rebrickable_dir: ../../brick_palettes_generator/data/rebrickable/
"""
import csv
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from _rebrickable_lookup import resolve_bl_part_nos_bulk
from dotenv import load_dotenv

load_dotenv()

try:
    DEFAULT_RB_DIR = Path(__file__).resolve().parents[2] / "brick_palettes_generator/data/rebrickable"
except IndexError:
    DEFAULT_RB_DIR = Path("rebrickable")

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def load_rb_colors(rb_dir: Path) -> dict[int, str]:
    """Return {rb_color_id: rb_color_name}."""
    colors: dict[int, str] = {}
    with open(rb_dir / "colors.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                colors[int(row["id"])] = row["name"]
            except (ValueError, KeyError):
                pass
    return colors


def load_bl_colors(conn) -> dict[str, int]:
    """Return {bl_name_lower: bl_id} from the DB colors table."""
    cur = conn.cursor()
    cur.execute("SELECT bl_id, bl_name FROM colors")
    result = {name.lower(): bl_id for bl_id, name in cur.fetchall()}
    cur.close()
    return result


def build_color_map(rb_colors: dict[int, str], bl_colors: dict[str, int]) -> dict[int, int]:
    """Return {rb_color_id: bl_color_id} matched by name."""
    mapping: dict[int, int] = {}
    for rb_id, rb_name in rb_colors.items():
        bl_id = bl_colors.get(rb_name.lower())
        if bl_id is not None:
            mapping[rb_id] = bl_id
    return mapping


def load_parts(rb_dir: Path) -> dict[str, str]:
    """Return {part_num: name} from parts.csv."""
    parts: dict[str, str] = {}
    with open(rb_dir / "parts.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pn = row.get("part_num", "").strip()
            name = row.get("name", "").strip()
            if pn and name:
                parts[pn] = name
    return parts


def main(rb_dir: Path = DEFAULT_RB_DIR) -> None:
    for fname in ("colors.csv", "parts.csv", "elements.csv"):
        if not (rb_dir / fname).exists():
            print(f"ERROR: {rb_dir / fname} not found", file=sys.stderr)
            sys.exit(1)
    if not REBRICKABLE_API_KEY:
        print("ERROR: REBRICKABLE_API_KEY not set — required to translate part numbers", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    print("Loading color mapping…")
    rb_colors = load_rb_colors(rb_dir)
    bl_colors = load_bl_colors(conn)
    color_map = build_color_map(rb_colors, bl_colors)
    mapped = len(color_map)
    total_rb = len(rb_colors)
    print(f"  {mapped}/{total_rb} Rebrickable colors mapped to BrickLink IDs")

    print("Loading parts.csv…")
    parts = load_parts(rb_dir)
    print(f"  {len(parts)} part names loaded")

    print("Processing elements.csv…")
    candidates: list[tuple] = []   # (element_id, design_id, rb_part_num, bl_color_id, part_name)
    skipped_color = 0
    skipped_name = 0

    with open(rb_dir / "elements.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                element_id = int(row["element_id"])
                rb_part_num = row["part_num"].strip()
                rb_color_id = int(row["color_id"])
                design_id = row.get("design_id", "").strip() or rb_part_num
            except (ValueError, KeyError):
                continue

            bl_color_id = color_map.get(rb_color_id)
            if bl_color_id is None:
                skipped_color += 1
                continue

            part_name = parts.get(rb_part_num)
            if not part_name:
                skipped_name += 1
                continue

            candidates.append((element_id, design_id, rb_part_num, bl_color_id, part_name))

    print(f"  {len(candidates)} candidates  "
          f"({skipped_color} skipped: unmapped color, {skipped_name} skipped: unknown part)")

    distinct_rb_part_nums = sorted({c[2] for c in candidates})
    print(f"Resolving {len(distinct_rb_part_nums)} distinct part numbers via Rebrickable's API…")
    bl_part_no_map = resolve_bl_part_nos_bulk(distinct_rb_part_nums, REBRICKABLE_API_KEY)
    print(f"  {len(bl_part_no_map)}/{len(distinct_rb_part_nums)} translated to a BrickLink part number")

    element_rows: list[tuple] = []   # (element_id, design_id)
    mapping_rows: list[tuple] = []   # (element_id, part_no, color_id, part_name, source)
    skipped_untranslated = 0
    for element_id, design_id, rb_part_num, bl_color_id, part_name in candidates:
        bl_part_no = bl_part_no_map.get(rb_part_num)
        if not bl_part_no:
            skipped_untranslated += 1
            continue
        element_rows.append((element_id, design_id))
        mapping_rows.append((element_id, bl_part_no, bl_color_id, part_name, "rebrickable"))

    print(f"  {len(element_rows)} elements to import ({skipped_untranslated} skipped: no BrickLink translation)")

    BATCH = 1000

    print("Inserting into lego_elements…")
    inserted_elements = 0
    for i in range(0, len(element_rows), BATCH):
        batch = element_rows[i : i + BATCH]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO lego_elements (element_id, design_id)
            VALUES %s
            ON CONFLICT (element_id) DO NOTHING
            """,
            batch,
            page_size=BATCH,
        )
        inserted_elements += cur.rowcount
    print(f"  {inserted_elements} new, {len(element_rows) - inserted_elements} already existed")

    print("Inserting into bricklink_mappings…")
    inserted_mappings = 0
    for i in range(0, len(mapping_rows), BATCH):
        batch = mapping_rows[i : i + BATCH]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bricklink_mappings (element_id, part_no, color_id, part_name, source)
            VALUES %s
            ON CONFLICT (element_id) DO NOTHING
            """,
            batch,
            page_size=BATCH,
        )
        inserted_mappings += cur.rowcount
    print(f"  {inserted_mappings} new, {len(mapping_rows) - inserted_mappings} already existed")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")
    print("Next: verify with psql, then deploy updated API (parts.py info-only fallback).")


if __name__ == "__main__":
    rb_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RB_DIR
    main(rb_dir)
