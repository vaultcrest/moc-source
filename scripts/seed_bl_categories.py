#!/usr/bin/env python3
"""Seed the bl_categories table from cache/bl_part_categories.json.

That JSON is a static, hand-curated list (BrickLink's Parts-catalog browse
page's <SELECT NAME="catID"> options, not an API endpoint -- BrickLink's own
GET /categories has no item-type filter, see alembic/versions/a9b0c1d2_bl_
categories.py), cross-verified live against GET /categories on 2026-07-15
(all 243 (id, name) pairs matched exactly). Re-run this after re-generating
that JSON if BrickLink adds new part categories in the future.

Run after `alembic upgrade head`.

Usage:
    DATABASE_URL=... python scripts/seed_bl_categories.py [path/to/bl_part_categories.json]
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "cache/bl_part_categories.json"

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def main(json_path: Path = DEFAULT_PATH) -> None:
    if not json_path.exists():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        sys.exit(1)

    categories = json.loads(json_path.read_text())
    rows = [(c["category_id"], c["category_name"], c["parent_id"]) for c in categories]

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO bl_categories (category_id, category_name, parent_id)
        VALUES %s
        ON CONFLICT (category_id) DO UPDATE SET
            category_name = EXCLUDED.category_name,
            parent_id     = EXCLUDED.parent_id
        """,
        rows,
        page_size=200,
    )
    print(f"  bl_categories: {len(rows)} rows upserted")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    main(path)
