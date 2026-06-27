#!/usr/bin/env python3
"""Seed the colors table from color_database.json.

Run after `alembic upgrade head`.

Usage:
    python scripts/seed_colors.py [path/to/color_database.json]
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DEFAULT_DB = Path(__file__).resolve().parents[2] / "brick_palettes_generator/data/color_database.json"

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def main(db_path: Path = DEFAULT_DB) -> None:
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(db_path.read_text())
    bl_entries = data.get("bricklink", {})

    rows = []
    for id_str, entry in bl_entries.items():
        bl = entry.get("bricklink", {})
        lego = entry.get("lego", {})
        bl_id = bl.get("id")
        bl_name = bl.get("name", "")
        if bl_id is None or not bl_name:
            continue
        lego_id = lego.get("id")
        lego_name = lego.get("name") or None
        # Skip empty LEGO names
        if lego_name == "":
            lego_name = None
        rows.append((bl_id, bl_name, lego_id, lego_name))

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO colors (bl_id, bl_name, lego_id, lego_name)
        VALUES %s
        ON CONFLICT (bl_id) DO UPDATE SET
            bl_name   = EXCLUDED.bl_name,
            lego_id   = EXCLUDED.lego_id,
            lego_name = EXCLUDED.lego_name
        """,
        rows,
        page_size=200,
    )
    print(f"  colors: {len(rows)} rows upserted")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    main(path)
