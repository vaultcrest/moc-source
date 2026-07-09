#!/usr/bin/env python3
"""Import Rebrickable's sets.csv into lego_sets.

Upserts on set_num so re-running against a refreshed sets.csv (new
Rebrickable export) updates existing rows in place — this is meant to be
run yearly by hand after dropping in a new sets.csv, plus a monthly
systemd timer that re-runs against whatever copy is already on disk to
pick up any manual mid-year replacement.

Usage:
    DATABASE_URL=... python scripts/import_sets_csv.py [path/to/sets.csv]

Default path: /opt/mocsource/data/sets.csv (where the infra playbook
deploys it), falling back to ../moc-source-infra/data/sets.csv for local dev.
"""
import csv
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

_SERVER_DEFAULT = Path("/opt/mocsource/data/sets.csv")
try:
    _DEV_DEFAULT = Path(__file__).resolve().parents[2] / "moc-source-infra" / "data" / "sets.csv"
except IndexError:
    _DEV_DEFAULT = Path("sets.csv")
DEFAULT_CSV_PATH = _SERVER_DEFAULT if _SERVER_DEFAULT.exists() else _DEV_DEFAULT

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BATCH = 1000


def load_sets(csv_path: Path) -> list[tuple]:
    rows: list[tuple] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            set_num = row.get("set_num", "").strip()
            if not set_num:
                continue
            name = row.get("name", "").strip() or None
            try:
                year = int(row["year"])
            except (ValueError, KeyError):
                year = None
            try:
                theme_id = int(row["theme_id"])
            except (ValueError, KeyError):
                theme_id = None
            try:
                num_parts = int(row["num_parts"])
            except (ValueError, KeyError):
                num_parts = None
            img_url = row.get("img_url", "").strip() or None
            rows.append((set_num, name, year, theme_id, num_parts, img_url))
    return rows


def main(csv_path: Path) -> None:
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {csv_path}…")
    rows = load_sets(csv_path)
    print(f"  {len(rows)} sets loaded")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    print("Upserting into lego_sets…")
    upserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO lego_sets (set_num, name, year, theme_id, num_parts, img_url, updated_at)
            VALUES %s
            ON CONFLICT (set_num) DO UPDATE SET
                name = EXCLUDED.name,
                year = EXCLUDED.year,
                theme_id = EXCLUDED.theme_id,
                num_parts = EXCLUDED.num_parts,
                img_url = EXCLUDED.img_url,
                updated_at = EXCLUDED.updated_at
            """,
            batch,
            template="(%s, %s, %s, %s, %s, %s, now())",
            page_size=BATCH,
        )
        upserted += len(batch)
        print(f"  {upserted}/{len(rows)}")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV_PATH
    main(path)
