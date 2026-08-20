#!/usr/bin/env python3
"""Generates Stud.io palette files directly from this DB -- replicates
brick_palettes_generator's build_palette()/export_outputs() (see that
project's generate_pab_inventory.py), but reading moc-source's own
lego_element_prices/bricklink_mappings/studio_resolutions/colors instead
of re-scraping LEGO/BrickLink/Rebrickable fresh each run.

Two fixed locales: en-us (NA) and de-de (EU) -- the same representative
locales moc-source's own nightly OOS-tracking already uses (OOS_LOCALES in
scripts/scrape_pab.py), confirmed via DB analysis that in-stock status is
identical across every locale within each region group. Not configurable
via a flag on purpose -- these are the two real regions Sean wants, not an
arbitrary default.

Palette file format (plain text, matches the original tool exactly):
    ~+{name}
    14
    -1
    0 {part_file}
    1 {bricklink_name}
    2 {ldraw_color_id}
repeated per part. Entries deduped by (part_file, ldraw_color_id). DUPLO
excluded by name substring, matching the original's own exclusion.

Bucketing: lego_element_prices carries both a nominal `channel`
(pab/bap/oos) and a separate `in_stock` boolean per locale -- in_stock is
the more accurate live-availability signal (a nominally-pab element can
currently be out of stock), so buckets combine both rather than trusting
channel alone:
    bestseller    = channel='pab' AND in_stock
    standard      = channel='bap' AND in_stock
    out_of_stock  = NOT in_stock
    all           = everything
    all_in_stock  = in_stock

Only parts with a resolved studio_resolutions row are included (matches
the original's `if not entry["studio"]["resolved"]: continue`) -- no
Studio geometry, no palette entry.

Entry order: grouped by BL category_id, then alphabetically by
display_name within each category (COLLATE "C" -- Postgres's default
locale collation weighs a digit as greater than a space, so e.g.
"Technic, Brick 1 x 10..." sorted before "1 x 1..." even though "1 x 1"
is a true string prefix and should sort first; forcing byte-order
comparison fixes this real bug, confirmed 2026-08-19 without breaking the
already-matched "Brick 1x1/1x2/1x3/1x4" sequence), then color. Confirmed
live this matches Stud.io's own "BL Categories" browser panel.
bl_part_catalog.catalog_sequence (P.xml row order) and
BLCatalogIndex/BLCatalogSubIndex (from brick_palettes_generator's
StudioPartDefinition2.txt) were both tried and rejected the same day --
neither reproduces this panel order (catalog_sequence disagrees on which
part comes first within a size family; the BLCatalogIndex/SubIndex pair
only buckets category/subcategory, all same-family parts share one value,
no finer ordering signal). Investigation ongoing -- see
project_studio_resolutions memory for where this stands.

Publishing (added 2026-08-20): after writing each locale's 5 bucket files,
also zips them (flat -- no locale-prefixed paths inside the zip, so a user
can extract straight into Stud.io's Buckets\\Folders\\ directory) into
`static/studio_palettes/<locale>.zip`, and writes a sibling
`manifest.json` (`generated_at` UTC timestamp + per-locale/bucket entry
counts) for the `/studio-palettes` website page to read. Both are served
automatically by the existing `/static` mount (`mocsource/main.py`) --
no new route needed. Driven by a new 4-hour systemd timer
(moc-source-infra) since the underlying query is cheap (current DB state
only, no scraping) -- see README.

Usage:
    DATABASE_URL=... python scripts/generate_studio_palettes.py
    DATABASE_URL=... python scripts/generate_studio_palettes.py --output-dir /path/to/output --publish-dir /path/to/static/studio_palettes
"""
import argparse
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

LOCALES = ["en-us", "de-de"]

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "studio_palettes"
DEFAULT_PUBLISH_DIR = Path(__file__).resolve().parent.parent / "static" / "studio_palettes"

QUERY = """
    SELECT
        lep.channel,
        lep.in_stock,
        sr.part_file,
        COALESCE(bm.part_name, bpc.name, le.lego_name, sr.part_file) AS display_name,
        bm.color_id,
        COALESCE(c.ldraw_id, bm.color_id) AS ldraw_color_id,
        (c.ldraw_id IS NULL) AS color_fallback,
        bpc.category_id,
        bpc.catalog_sequence
    FROM lego_element_prices lep
    JOIN bricklink_mappings bm ON bm.element_id = lep.element_id
    JOIN studio_resolutions sr ON sr.part_no = bm.part_no AND sr.resolved = true
    LEFT JOIN bl_part_catalog bpc ON bpc.part_no = bm.part_no
    LEFT JOIN lego_elements le ON le.element_id = lep.element_id
    LEFT JOIN colors c ON c.bl_id = bm.color_id
    WHERE lep.locale = %s AND bm.part_no IS NOT NULL
    ORDER BY bpc.category_id NULLS LAST,
             COALESCE(bm.part_name, bpc.name, le.lego_name, sr.part_file) COLLATE "C",
             ldraw_color_id
"""


def build_palette_text(rows, name):
    lines = [f"~+{name}", "14", "-1"]
    seen = set()
    for row in rows:
        part_file = row["part_file"]
        display_name = row["display_name"] or part_file
        if "duplo" in display_name.lower():
            continue
        # ldraw_color_id is already COALESCE(colors.ldraw_id, bl_color_id) from
        # the query -- this naturally reproduces resolve_studio_color()'s
        # None/0 -> 0 special case too, since bm.color_id itself is 0 there.
        color_id = row["ldraw_color_id"] if row["ldraw_color_id"] is not None else 0
        key = (part_file, color_id)
        if key in seen:
            continue
        seen.add(key)
        display_name = display_name.replace("&", " and ").replace("–", "-").replace("—", "-")
        lines.append(f"0 {part_file}")
        lines.append(f"1 {display_name}")
        lines.append(f"2 {color_id}")
    return "\n".join(lines), len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--publish-dir", type=Path, default=DEFAULT_PUBLISH_DIR)
    parser.add_argument("--no-publish", action="store_true",
                         help="skip zipping/manifest -- write the raw bucket files only")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "locales": {}}

    for locale in LOCALES:
        cur.execute(QUERY, (locale,))
        cols = [d[0] for d in cur.description]
        all_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        buckets = {
            "bestseller": [r for r in all_rows if r["channel"] == "pab" and r["in_stock"]],
            "standard": [r for r in all_rows if r["channel"] == "bap" and r["in_stock"]],
            "out_of_stock": [r for r in all_rows if not r["in_stock"]],
            "all": all_rows,
            "all_in_stock": [r for r in all_rows if r["in_stock"]],
        }

        locale_dir = args.output_dir / locale
        locale_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{locale}] {len(all_rows)} resolved PAB row(s) total")
        bucket_counts = {}
        written_paths = []
        for bucket_name, rows in buckets.items():
            palette_name = "Pick a Brick " + bucket_name.replace("_", " ").title()
            text, entry_count = build_palette_text(rows, palette_name)
            fallback_count = sum(1 for r in rows if r["color_fallback"])
            out_path = locale_dir / palette_name
            out_path.write_text(text, encoding="utf-8")
            written_paths.append(out_path)
            bucket_counts[bucket_name] = entry_count
            print(f"  {palette_name}: {entry_count} unique part/color entries "
                  f"({fallback_count} color(s) fell back to raw BL id, no LDraw mapping) -> {out_path}")

        manifest["locales"][locale] = {"total_resolved": len(all_rows), "buckets": bucket_counts}

        if not args.no_publish:
            args.publish_dir.mkdir(parents=True, exist_ok=True)
            zip_path = args.publish_dir / f"{locale}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in written_paths:
                    zf.write(p, arcname=p.name)  # flat -- extracts straight into Buckets\Folders\
            print(f"  -> published {zip_path}")

    cur.close()
    conn.close()

    if not args.no_publish:
        args.publish_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = args.publish_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\nWrote {manifest_path}")


if __name__ == "__main__":
    main()
