#!/usr/bin/env python3
"""Reports BrickLink parts we don't know about at all.

Compares brickstore_part_catalog (the full real BrickLink Parts catalog,
ingested by scripts/ingest_brickstore_catalog.py) against bricklink_mappings
(our own curated, naturally partial subset) to find genuine catalog gaps.

Excludes sticker-sheet-type categories (pure decal sheets, not physical
parts/molds) -- determined dynamically by scanning brickstore_part_catalog
category names for "sticker", not hardcoded, since a defensive check found
one category ("Stickered Assembly") that matches the word but is actually a
real physical part and must NOT be excluded (confirmed live 2026-07-16:
category_id 160 "Sticker Sheet" has 4,950 parts and is a real exclusion;
category_id 582 "Stickered Assembly" has 710 parts and is not -- it's an
assembled/decorated physical part, e.g. "Stickered Assembly 3x2x1 2/3 with
Shell Tank Number 2 Pattern - Set 6610"). Only category names ending in
"Sheet" or "Book" or matching "Sticker, " (collectible loose stickers) are
excluded -- reviewed by hand against the real category list, not guessed.

Read-only. Reports to console, writes cache/bl_catalog_gaps.csv, and emails
a summary via the existing SMTP convention (SMTP_HOST/REPORT_EMAIL, no-op if
unset).

Usage:
    DATABASE_URL=... python scripts/analyze_bl_catalog_gaps.py
"""
import csv
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "bl_catalog_gaps.csv"

# Reviewed by hand against the real category list (2026-07-16) -- these
# patterns match sheet/book/loose-sticker product categories, not physical
# parts. "Stickered Assembly" deliberately does NOT match any of these.
STICKER_CATEGORY_NAME_PATTERNS = ["Sticker Sheet", "Sticker Book", "Sticker, %"]

FIND_STICKER_CATEGORIES_SQL = """
    SELECT DISTINCT category_id FROM brickstore_part_catalog
    WHERE category_id IN (
        SELECT category_id FROM bl_categories WHERE category_name ILIKE ANY(%s)
    )
"""
# bl_categories may not have every category from this release's fuller category
# list -- fall back to matching brickstore_part_catalog's own rows directly by
# joining against categories.xml isn't done here (bl_categories is parts-only
# and close enough); if bl_categories is missing a match this just excludes
# nothing extra, never excludes something it shouldn't.

GAP_SQL = """
    SELECT bpc.part_no, bpc.category_id, bpc.name
    FROM brickstore_part_catalog bpc
    WHERE NOT EXISTS (
        SELECT 1 FROM bricklink_mappings bm WHERE bm.part_no = bpc.part_no
    )
    AND (%(sticker_ids)s = '{}' OR bpc.category_id != ALL(%(sticker_ids)s))
    ORDER BY bpc.part_no
"""


def send_report(gap_count: int, sticker_excluded: int, total_parts: int) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    body = (
        f"BrickLink catalog gap analysis (brickstore_part_catalog vs bricklink_mappings)\n\n"
        f"Total real BrickLink parts known: {total_parts:,}\n"
        f"Sticker-category parts excluded : {sticker_excluded:,}\n"
        f"Parts we have no mapping for    : {gap_count:,}\n\n"
        f"Full list: cache/bl_catalog_gaps.csv on the app server.\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"[MOC Source] BL catalog gap analysis: {gap_count:,} unmapped parts"
    msg["From"]    = smtp_from
    msg["To"]      = report_email
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(smtp_from, [report_email], msg.as_string())
        print(f"Report emailed to {report_email}")
    except Exception as e:
        print(f"Failed to send report email: {e}", file=sys.stderr)


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM brickstore_part_catalog")
    total_parts = cur.fetchone()[0]

    cur.execute(FIND_STICKER_CATEGORIES_SQL, (STICKER_CATEGORY_NAME_PATTERNS,))
    sticker_ids = [r[0] for r in cur.fetchall()]
    print(f"Excluding sticker categories: {sticker_ids}")

    cur.execute("SELECT count(*) FROM brickstore_part_catalog WHERE category_id = ANY(%s)", (sticker_ids,))
    sticker_excluded = cur.fetchone()[0]

    cur.execute(GAP_SQL, {"sticker_ids": sticker_ids})
    gaps = cur.fetchall()

    cur.close()
    conn.close()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["part_no", "category_id", "name"])
        writer.writerows(gaps)

    print(f"\nTotal real BrickLink parts: {total_parts:,}")
    print(f"Sticker-category parts excluded: {sticker_excluded:,}")
    print(f"Parts with no bricklink_mappings entry: {len(gaps):,}")
    print(f"Written to {CACHE_PATH}")

    send_report(len(gaps), sticker_excluded, total_parts)


if __name__ == "__main__":
    main()
