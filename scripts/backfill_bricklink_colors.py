#!/usr/bin/env python3
"""Backfill colors.color_type and insert any BrickLink colors missing from
the colors table, from BrickLink's own GET /colors catalog.

The colors table was originally seeded from BrickLink Studio's
CustomColorDefinition.txt (see seed_colors.py / build_color_database.py),
which does not carry BrickLink's own color_type classification (Solid,
Transparent, Modulex, Pearl, Chrome, Satin, Glitter, Metallic, Milky,
Speckle) and is missing some colors BrickLink's live catalog has (confirmed
2026-07-14: 44 missing, mostly the "Mx" Modulex sub-brand).

Additive only: existing rows only ever get color_type written (never
bl_name/hex/lego_id/lego_name/rebrickable_id); new rows are inserted with
ON CONFLICT (bl_id) DO NOTHING as a safety net on top of the pre-checked
missing-id list, so this can never overwrite an existing row.

Usage:
    DATABASE_URL=... BRICKLINK_CONSUMER_KEY=... BRICKLINK_CONSUMER_SECRET=... \\
    BRICKLINK_TOKEN=... BRICKLINK_TOKEN_SECRET=... python scripts/backfill_bricklink_colors.py [--dry-run]
"""
import argparse
import os
import sys

import psycopg2
from _bricklink_lookup import BLClient
from dotenv import load_dotenv

load_dotenv()

BRICKLINK_CONSUMER_KEY = os.environ.get("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.environ.get("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.environ.get("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.environ.get("BRICKLINK_TOKEN_SECRET", "")

bl_client = BLClient(BRICKLINK_CONSUMER_KEY, BRICKLINK_CONSUMER_SECRET, BRICKLINK_TOKEN, BRICKLINK_TOKEN_SECRET)

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    print("Fetching BrickLink colors catalog...")
    attempted, bl_colors = bl_client.fetch_colors()
    if not attempted or bl_colors is None:
        print("ERROR: BrickLink colors catalog fetch failed", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(bl_colors)} BrickLink colors fetched")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT bl_id FROM colors")
    existing_ids = {row[0] for row in cur.fetchall()}

    updated = 0
    inserted: list[tuple[int, str, str]] = []
    for c in bl_colors:
        bl_id = c["color_id"]
        bl_name = c["color_name"]
        hex_code = (c.get("color_code") or "").upper()
        color_type = c.get("color_type")

        if bl_id in existing_ids:
            updated += 1
            if args.dry_run:
                print(f"    [dry-run] update bl_id={bl_id} ({bl_name}) -> color_type={color_type}")
            else:
                cur.execute("UPDATE colors SET color_type = %s WHERE bl_id = %s", (color_type, bl_id))
        else:
            inserted.append((bl_id, bl_name, color_type))
            if args.dry_run:
                print(f"    [dry-run] insert bl_id={bl_id} ({bl_name}) hex={hex_code} color_type={color_type}")
            else:
                cur.execute(
                    """
                    INSERT INTO colors (bl_id, bl_name, hex, color_type)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (bl_id) DO NOTHING
                    """,
                    (bl_id, bl_name, hex_code, color_type),
                )

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone. {updated} existing rows updated with color_type, {len(inserted)} new rows inserted.")
    if inserted:
        print("Newly inserted BrickLink colors:")
        for bl_id, bl_name, color_type in inserted:
            print(f"  bl_id={bl_id}  bl_name={bl_name}  color_type={color_type}")


if __name__ == "__main__":
    main()
