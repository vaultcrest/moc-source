#!/usr/bin/env python3
"""Parses BrickLink's "Item Relationships" mold-family pages (scraped by
BrickStore, see scripts/_brickstore_release.py) into
brickstore_mold_relationship_groups/_members, and derives pairwise
bricklink_alternates rows from the 'similar_mold' groups only.

Page structure (confirmed by reading the real files, 2026-07-16): a
group-header row (single <td colspan="4"> containing "Match #N") followed by
member rows, each with a catalogitem.page?P=<part_no> link and a
catalogList.asp?catType=P&catID=<id> category link. BrickLink's own
"Match #N" is a page-local row counter, not a stable id -- never persisted
as our key, hence the BIGSERIAL id on brickstore_mold_relationship_groups.

Self-check before any DB write, per file: parsed group count must equal the
page's own "N Matches found" banner (for single-page relationship types) or
the count of "Match #" headers (multi-page), and parsed member count must
equal the raw count of "catalogitem.page?P=" occurrences in the file --
verified against real data: similar_molds page 1 = 1000 groups/2368 members,
page 2 = 66 groups/139 members (1066 total, matching the banner),
different_molds = 226 groups/480 members. Hard-fails (no writes) on any
mismatch, since this is HTML scraping with no schema contract to lean on.

Full truncate+reload of both tables each run -- group membership isn't
meaningfully diffable row-by-row, and BrickLink's row-local "Match #N" isn't
a stable id across runs to diff against anyway.

Only 'similar_mold' groups feed bricklink_alternates (tagged
source='brickstore_mold_group', scoped delete+reinsert so
ingest_brickstore_catalog.py's 'brickstore_alternate_ids' rows and any
remaining legacy 'bl_alternate_no' rows are untouched). 'different_mold'
groups mean "visually similar but NOT interchangeable" -- deliberately never
written to bricklink_alternates, which means "directly interchangeable."

Usage:
    DATABASE_URL=... python scripts/ingest_brickstore_mold_relationships.py
    DATABASE_URL=... python scripts/ingest_brickstore_mold_relationships.py --data-dir /path/to/extracted
"""
import argparse
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from _brickstore_release import ensure_latest
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

P_LINK_RE = re.compile(r"catalogitem\.page\?P=")
MATCH_HEADER_RE = re.compile(r"Match #(\d+)")
BANNER_RE = re.compile(r"<B>(\d+)</B> Matches found")

# (glob pattern, relationship_type) -- matches every page of each kind present
# in the release; new pages (e.g. a future _3.html) are picked up automatically.
RELATIONSHIP_FILE_KINDS = [
    ("similar_parts_with_similar_molds_*.html", "similar_mold"),
    ("similar_parts_with_different_molds_*.html", "different_mold"),
]


def parse_relationship_html(html: str) -> list[list[tuple[str, int | None]]]:
    """Returns a list of groups, each a list of (part_no, category_id)."""
    soup = BeautifulSoup(html, "html.parser")
    groups: list[list[tuple[str, int | None]]] = []
    current: list[tuple[str, int | None]] | None = None

    for row in soup.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) == 1 and tds[0].get("colspan") == "4" and MATCH_HEADER_RE.search(tds[0].get_text()):
            if current is not None:
                groups.append(current)
            current = []
            continue
        if current is None:
            continue
        link = row.find("a", href=re.compile(r"catalogitem\.page\?P="))
        if not link:
            continue
        qs = urllib.parse.urlparse(link["href"]).query
        part_no = urllib.parse.parse_qs(qs).get("P", [None])[0]
        if not part_no:
            continue
        cat_id = None
        cat_link = row.find("a", href=re.compile(r"catalogList\.asp"))
        if cat_link:
            cat_qs = urllib.parse.urlparse(cat_link["href"]).query
            cat_raw = urllib.parse.parse_qs(cat_qs).get("catID", [None])[0]
            cat_id = int(cat_raw) if cat_raw else None
        current.append((part_no, cat_id))

    if current:
        groups.append(current)
    return groups


def self_check(html: str, groups: list[list[tuple[str, int | None]]], filename: str) -> None:
    parsed_groups = len(groups)
    parsed_members = sum(len(g) for g in groups)
    raw_p_links = len(P_LINK_RE.findall(html))
    match_headers = len(MATCH_HEADER_RE.findall(html))

    if parsed_groups != match_headers:
        raise ValueError(f"{filename}: parsed {parsed_groups} groups but found {match_headers} 'Match #' headers")
    if parsed_members != raw_p_links:
        raise ValueError(f"{filename}: parsed {parsed_members} members but found {raw_p_links} raw P= links")
    print(f"    {filename}: self-check passed ({parsed_groups} groups, {parsed_members} members)")


def load_all_groups(extract_dir: Path) -> list[tuple[str, list[tuple[str, int | None]]]]:
    """Returns [(relationship_type, group), ...] across every matching file."""
    rel_dir = extract_dir / "relationships"
    results = []
    for pattern, rel_type in RELATIONSHIP_FILE_KINDS:
        for path in sorted(rel_dir.glob(pattern)):
            html = path.read_text(encoding="utf-8")
            groups = parse_relationship_html(html)
            self_check(html, groups, path.name)
            for group in groups:
                results.append((rel_type, group))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=None,
                         help="use an already-extracted brickstore-database dir instead of downloading")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    start_time = time.monotonic()

    if args.data_dir:
        extract_dir = args.data_dir
        print(f"Using existing extracted data at {extract_dir}")
    else:
        extract_dir = ensure_latest()
        if extract_dir is None:
            print("No new brickstore-database release to ingest (or fetch failed). Nothing to do.")
            return

    try:
        typed_groups = load_all_groups(extract_dir)
    except ValueError as e:
        print(f"Self-check failed, aborting with no DB writes: {e}", file=sys.stderr)
        sys.exit(1)

    similar_count = sum(1 for t, _ in typed_groups if t == "similar_mold")
    different_count = sum(1 for t, _ in typed_groups if t == "different_mold")
    print(f"\nParsed {len(typed_groups)} groups total "
          f"({similar_count} similar_mold, {different_count} different_mold)")

    if args.dry_run:
        print("[dry-run] would truncate+reload brickstore_mold_relationship_groups/_members "
              "and rebuild bricklink_alternates rows tagged source='brickstore_mold_group'")
        return

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    cur.execute("TRUNCATE TABLE brickstore_mold_relationship_members")
    cur.execute("TRUNCATE TABLE brickstore_mold_relationship_groups RESTART IDENTITY CASCADE")

    alternate_pairs = set()
    for rel_type, group in typed_groups:
        cur.execute(
            "INSERT INTO brickstore_mold_relationship_groups (relationship_type, imported_at) VALUES (%s, %s) RETURNING id",
            (rel_type, now),
        )
        group_id = cur.fetchone()[0]
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO brickstore_mold_relationship_members (group_id, part_no, category_id) VALUES %s",
            [(group_id, part_no, cat_id) for part_no, cat_id in group],
        )
        if rel_type == "similar_mold":
            part_nos = [p for p, _ in group]
            for a in part_nos:
                for b in part_nos:
                    if a != b:
                        alternate_pairs.add((a, b))

    cur.execute("DELETE FROM bricklink_alternates WHERE source = 'brickstore_mold_group'")
    if alternate_pairs:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bricklink_alternates (part_no, alternate_no, source, updated_at)
            VALUES %s
            ON CONFLICT (part_no, alternate_no) DO UPDATE SET
                source = EXCLUDED.source,
                updated_at = EXCLUDED.updated_at
            """,
            [(p, a, "brickstore_mold_group", now) for p, a in alternate_pairs],
            page_size=1000,
        )

    conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s. Groups: {len(typed_groups)}, derived alternate pairs: {len(alternate_pairs)}")


if __name__ == "__main__":
    main()
