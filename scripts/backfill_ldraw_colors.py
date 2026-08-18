#!/usr/bin/env python3
"""One-time backfill of colors.ldraw_id/ldraw_name from
brick_palettes_generator's color_database.json (Sean's sibling project --
see scripts/generate_studio_palettes.py for why this mapping is needed).

Not a recurring job -- that reference file only changes when Sean updates
it by hand from a real Studio/LDraw install. Safe to re-run (plain UPDATE,
idempotent).

Usage:
    DATABASE_URL=... python scripts/backfill_ldraw_colors.py [--dry-run]
    DATABASE_URL=... python scripts/backfill_ldraw_colors.py --color-db /path/to/color_database.json
"""
import argparse
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

DEFAULT_COLOR_DB = Path("/home/excalibrax/projects/brick_palettes_generator/data/color_database.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--color-db", type=Path, default=DEFAULT_COLOR_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.color_db.read_text())
    bricklink = data.get("bricklink", {})

    rows = []
    for bl_id_str, entry in bricklink.items():
        ldraw = entry.get("ldraw")
        if not ldraw:
            continue
        try:
            bl_id = int(bl_id_str)
        except ValueError:
            continue
        rows.append((bl_id, ldraw.get("id"), ldraw.get("name")))

    print(f"{len(rows)} BrickLink color(s) with an LDraw mapping in {args.color_db}")

    if args.dry_run:
        for bl_id, ldraw_id, ldraw_name in rows[:10]:
            print(f"  [dry-run] bl_id={bl_id} -> ldraw_id={ldraw_id} ldraw_name={ldraw_name}")
        print(f"  [dry-run] ... {len(rows)} total")
        return

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    updated = 0
    for bl_id, ldraw_id, ldraw_name in rows:
        cur.execute(
            "UPDATE colors SET ldraw_id = %s, ldraw_name = %s WHERE bl_id = %s",
            (ldraw_id, ldraw_name, bl_id),
        )
        updated += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    print(f"Done. {updated}/{len(rows)} colors rows updated (rest had no matching bl_id in our colors table).")


if __name__ == "__main__":
    main()
