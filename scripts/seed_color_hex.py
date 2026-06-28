"""Populate colors.hex from the Rebrickable color API.

Fetches all Rebrickable colors, cross-references BrickLink IDs via
external_ids.BrickLink.ext_ids, and updates the hex column for matching rows.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/seed_color_hex.py
"""

import os
import sys

import psycopg2
import requests

_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
RB_KEY = os.environ.get("REBRICKABLE_API_KEY")

if not DATABASE_URL or not RB_KEY:
    sys.exit("DATABASE_URL and REBRICKABLE_API_KEY must be set")


def fetch_rb_colors() -> dict[int, str]:
    """Return mapping of BL color ID → hex string (6 chars, no #)."""
    bl_to_hex: dict[int, str] = {}
    url = f"https://rebrickable.com/api/v3/lego/colors/?key={RB_KEY}&page_size=300"
    while url:
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for color in data.get("results", []):
            rgb = (color.get("rgb") or "").strip()
            if not rgb or len(rgb) != 6:
                continue
            bl_ids = color.get("external_ids", {}).get("BrickLink", {}).get("ext_ids", [])
            for bl_id in bl_ids:
                if bl_id is not None:
                    bl_to_hex[int(bl_id)] = rgb.upper()
        url = data.get("next")
    return bl_to_hex


def main() -> None:
    bl_to_hex = fetch_rb_colors()
    print(f"Fetched {len(bl_to_hex)} BL color → hex mappings from Rebrickable")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bl_id FROM colors")
            rows = cur.fetchall()
            updated = 0
            skipped = 0
            for (bl_id,) in rows:
                hex_val = bl_to_hex.get(bl_id)
                if hex_val:
                    cur.execute("UPDATE colors SET hex = %s WHERE bl_id = %s", (hex_val, bl_id))
                    updated += 1
                else:
                    skipped += 1
        conn.commit()
    finally:
        conn.close()

    print(f"Updated: {updated}  |  No RB match: {skipped}")


if __name__ == "__main__":
    main()
