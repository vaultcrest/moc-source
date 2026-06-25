#!/usr/bin/env python3
"""Seed Phase 1 tables from canonical_mapping.json.

Populates: lego_elements, bricklink_mappings, bricklink_alternates, studio_resolutions.
Run after `alembic upgrade head`.

Usage:
    python scripts/seed.py [path/to/canonical_mapping.json]
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

DEFAULT_MAPPING = Path(__file__).resolve().parents[2] / "brick_palettes_generator/cache/canonical_mapping.json"

# seed.py uses psycopg2 (sync) — simpler for a one-shot script.
# DATABASE_URL is asyncpg format; rewrite for psycopg2.
_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def main(mapping_path: Path = DEFAULT_MAPPING) -> None:
    if not mapping_path.exists():
        print(f"ERROR: {mapping_path} not found", file=sys.stderr)
        sys.exit(1)

    data: dict = json.loads(mapping_path.read_text())
    print(f"Seeding {len(data)} entries from {mapping_path} ...")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    elements = []
    bl_mappings = []
    bl_alternates = []
    studio_seen: dict[str, dict] = {}  # part_no → studio data (deduplicated)

    for element_id_str, entry in data.items():
        element_id = int(element_id_str)
        lego = entry.get("lego", {})
        bl = entry.get("bricklink", {})
        studio = entry.get("studio", {})
        price = entry.get("price", {})

        elements.append((
            element_id,
            lego.get("design_id"),
            lego.get("name"),
            entry.get("channel"),
            price.get("cent_amount"),
            price.get("formatted"),
            NOW,
            NOW,
            NOW,
        ))

        if bl:
            part_no = bl.get("part_no")
            bl_mappings.append((
                element_id,
                part_no,
                bl.get("color_id"),
                bl.get("item_type"),
                bl.get("name"),
                entry.get("source"),
                NOW,
            ))

            for alt in bl.get("alternate_no", []):
                if part_no and alt:
                    bl_alternates.append((part_no, str(alt)))

            # studio_resolutions keyed by part_no — deduplicate across elements
            if studio and part_no and part_no not in studio_seen:
                studio_seen[part_no] = {
                    "part_no": part_no,
                    "part_file": studio.get("part_file"),
                    "source_type": studio.get("source_type"),
                    "resolution_method": studio.get("resolution_method"),
                    "resolved_from": studio.get("resolved_from"),
                    "studio_color_id": studio.get("color_id"),
                    "resolved": studio.get("resolved", False),
                }

    # Bulk upsert lego_elements
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO lego_elements
            (element_id, design_id, lego_name, channel, price_cents, price_formatted, last_seen, first_seen, updated_at)
        VALUES %s
        ON CONFLICT (element_id) DO UPDATE SET
            design_id       = EXCLUDED.design_id,
            lego_name       = EXCLUDED.lego_name,
            channel         = EXCLUDED.channel,
            price_cents     = EXCLUDED.price_cents,
            price_formatted = EXCLUDED.price_formatted,
            last_seen       = EXCLUDED.last_seen,
            updated_at      = EXCLUDED.updated_at
        """,
        elements,
        page_size=500,
    )
    print(f"  lego_elements:       {len(elements):>6}")

    # Bulk upsert bricklink_mappings
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO bricklink_mappings
            (element_id, part_no, color_id, item_type, part_name, source, updated_at)
        VALUES %s
        ON CONFLICT (element_id) DO UPDATE SET
            part_no    = EXCLUDED.part_no,
            color_id   = EXCLUDED.color_id,
            item_type  = EXCLUDED.item_type,
            part_name  = EXCLUDED.part_name,
            source     = EXCLUDED.source,
            updated_at = EXCLUDED.updated_at
        """,
        bl_mappings,
        page_size=500,
    )
    print(f"  bricklink_mappings:  {len(bl_mappings):>6}")

    # Bulk upsert bricklink_alternates (deduplicate in Python first)
    unique_alts = list({(p, a) for p, a in bl_alternates})
    if unique_alts:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bricklink_alternates (part_no, alternate_no)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            unique_alts,
            page_size=500,
        )
    print(f"  bricklink_alternates:{len(unique_alts):>6}")

    # Bulk upsert studio_resolutions
    studio_rows = [(v["part_no"], v["part_file"], v["source_type"], v["resolution_method"], v["resolved_from"], v["studio_color_id"], v["resolved"]) for v in studio_seen.values()]
    if studio_rows:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO studio_resolutions
                (part_no, part_file, source_type, resolution_method, resolved_from, studio_color_id, resolved)
            VALUES %s
            ON CONFLICT (part_no) DO UPDATE SET
                part_file         = EXCLUDED.part_file,
                source_type       = EXCLUDED.source_type,
                resolution_method = EXCLUDED.resolution_method,
                resolved_from     = EXCLUDED.resolved_from,
                studio_color_id   = EXCLUDED.studio_color_id,
                resolved          = EXCLUDED.resolved
            """,
            studio_rows,
            page_size=500,
        )
    print(f"  studio_resolutions:  {len(studio_rows):>6}")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MAPPING
    main(path)
