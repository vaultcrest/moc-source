#!/usr/bin/env python3
"""Resumable retry pass for real BrickLink part_nos with zero bricklink_mappings
row at all -- the opposite direction from fix_rebrickable_part_nos.py, which
repairs existing-but-wrong rows written with Rebrickable's own numbering.

Root cause (found 2026-07-21): import_rebrickable.py only writes a
bricklink_mappings row when Rebrickable's own data already has a
BrickLink translation for the element it's importing -- untranslated
elements are silently skipped, never written. So a BrickLink part never
gets a row at all when Rebrickable's catalog simply hasn't indexed that
exact part_no under any numbering scheme reachable via elements.csv (a gap
scripts/download_rebrickable_data.py's periodic refresh alone can't close,
since it depends on Rebrickable having resolved the translation already).

Confirmed live 2026-07-21: Rebrickable's /lego/parts/ list endpoint
supports an undocumented but real, exact-match reverse-lookup filter,
bricklink_id=<bl_part_no> -- see resolve_bl_part_no_reverse() in
_rebrickable_lookup.py for the verification details. Single-value only (no
comma-batching, no repeated-key multi-value), so this is one API call per
candidate, no bulk form exists -- at 1.2s pacing the full backlog
(~52,528 part_nos as of 2026-07-21) is ~17.5 hours of API time, so this is
designed to run in small nightly batches via --batch-size, not a single
supervised pass like fix_rebrickable_part_nos.py.

A successful reverse-lookup match only returns a Rebrickable part_num, not
bricklink_mappings-ready data (that table is keyed on element_id). Full
flow per match, confirmed live:
  1. bricklink_id=<bl_part_no> -> rb part_num
  2. /lego/parts/{rb_part_num}/colors/ -> element_ids per color (can be
     empty for very obscure/vintage parts -- a legitimate "no element
     data" outcome, not an error)
  3. resolve_element_via_rebrickable(element_id) per returned element_id
     -> BL color_id + year data, to build the real bricklink_mappings row

Priority: plain parts before printed/decorated ones (Sean's explicit call
2026-07-21). Printed/decorated variants are both the largest share of the
gap and the class of part where Rebrickable/BrickLink numbering diverges
hardest (every renumbering case found this session was a print variant),
so they're the least likely to resolve cleanly per attempt -- plain parts
are a smaller, higher-value-per-attempt target. is_printed is computed
fresh from bl_categories.category_name + part_no suffix pattern (mirrors
scripts/analyze_bl_catalog_gaps.py's gap-finding query and sticker-category
exclusion, kept in sync by hand since these are separate top-level
scripts, not a shared module) at selection time -- so a brand-new
candidate is correctly tiered immediately, no backfill needed as the gap
changes over time.

is_low_priority (added 2026-07-22, Sean's call): BrickLink "c" + number
suffix parts (e.g. 08010ac01 -- BrickLink's "Complete assembly" marker) and
Baseplate-category parts sink behind BOTH the plain and printed tiers.
Confirmed by hand: 08010ac01/08010bc02 aren't unmapped because Rebrickable
never indexed them, they're unmapped because BrickLink itself has
superseded/deprecated them in favor of newer part numbers for the same
physical assembly (08010ac01 -> 265bc01, 08010bc02 -> 266bc02) -- a
reverse lookup on the dead part_no will legitimately find nothing even
though Rebrickable has good data under the replacement number. These are
real candidates, just much less likely to resolve per attempt, so they
shouldn't compete with the rest of the backlog for nightly budget.

Same "never permanently done" philosophy as rebrickable_part_no_fixes --
unresolved rows stay retry-eligible (deprioritized behind never-attempted
rows within their own is_printed tier), since Rebrickable's catalog keeps
growing.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/reverse_map_bl_catalog.py [--batch-size N] [--dry-run]
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/reverse_map_bl_catalog.py --part-no 08010ac01 [--dry-run]
"""
import argparse
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg2
from _rebrickable_lookup import (
    resolve_bl_part_no_reverse,
    resolve_element_via_rebrickable,
    resolve_part_colors_elements,
)
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
INTER_CALL_DELAY = 1.2
DEFAULT_BATCH_SIZE = 3000  # up to 3 calls/candidate worst case + 1.2s pacing -> roughly 1-3hr/run depending on match rate

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

# Mirrors scripts/analyze_bl_catalog_gaps.py's STICKER_CATEGORY_NAME_PATTERNS
# exactly -- keep in sync by hand if that script's exclusion list changes.
STICKER_CATEGORY_NAME_PATTERNS = ["Sticker Sheet", "Sticker Book", "Sticker, %"]

FIND_STICKER_CATEGORIES_SQL = """
    SELECT DISTINCT category_id FROM brickstore_part_catalog
    WHERE category_id IN (
        SELECT category_id FROM bl_categories WHERE category_name ILIKE ANY(%s)
    )
"""

# is_printed: either a "Decorated"/"Printed" category name, or a printed-style
# part_no suffix (pb/pat/pr followed by digits) -- combined signal, confirmed
# live 2026-07-21 against the real gap: 45,693/52,678 (87%) match at least one,
# 6,985 (13%) match neither and are the priority target.
#
# is_low_priority: a "c" + number suffix (BrickLink's "Complete assembly"
# marker, e.g. ac01/bc02) or a Baseplate-category part -- both disproportion-
# ately represent BrickLink part_nos that have been superseded/deprecated on
# BrickLink's own side (see module docstring), so they sink behind both the
# plain and printed tiers rather than compete for the same nightly budget.
CANDIDATES_CTE = """
    candidates AS (
        SELECT bpc.part_no,
            (bc.category_name ILIKE '%%decorated%%' OR bc.category_name ILIKE '%%printed%%'
             OR bpc.part_no ~ 'pb[0-9]+' OR bpc.part_no ~ 'pat[0-9]+' OR bpc.part_no ~ 'pr[0-9]+') AS is_printed,
            (bpc.part_no ~ 'c[0-9]+$' OR bc.category_name ILIKE '%%baseplate%%') AS is_low_priority
        FROM brickstore_part_catalog bpc
        LEFT JOIN bl_categories bc ON bc.category_id = bpc.category_id
        WHERE NOT EXISTS (SELECT 1 FROM bricklink_mappings bm WHERE bm.part_no = bpc.part_no)
        AND (%(sticker_ids)s = '{}' OR bpc.category_id != ALL(%(sticker_ids)s))
    )
"""

BATCH_SQL = f"""
    WITH {CANDIDATES_CTE}
    SELECT c.part_no, c.is_printed, c.is_low_priority
    FROM candidates c
    LEFT JOIN bl_catalog_gap_fixes f ON f.old_part_no = c.part_no
    WHERE f.old_part_no IS NULL OR f.method = 'unresolved'
    ORDER BY c.is_low_priority ASC, c.is_printed ASC, f.attempted_at ASC NULLS FIRST, c.part_no
    LIMIT %(limit)s
"""

COUNT_SQL = f"""
    WITH {CANDIDATES_CTE}
    SELECT c.is_low_priority, c.is_printed, count(*)
    FROM candidates c
    LEFT JOIN bl_catalog_gap_fixes f ON f.old_part_no = c.part_no
    WHERE f.old_part_no IS NULL OR f.method = 'unresolved'
    GROUP BY c.is_low_priority, c.is_printed
"""

UPSERT_FIX_SQL = """
    INSERT INTO bl_catalog_gap_fixes
        (old_part_no, rb_part_num, is_printed, is_low_priority, method, elements_created, attempted_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (old_part_no) DO UPDATE SET
        rb_part_num = EXCLUDED.rb_part_num,
        is_printed = EXCLUDED.is_printed,
        is_low_priority = EXCLUDED.is_low_priority,
        method = EXCLUDED.method,
        elements_created = EXCLUDED.elements_created,
        attempted_at = EXCLUDED.attempted_at
"""

INSERT_ELEMENT_SQL = """
    INSERT INTO lego_elements (element_id, design_id)
    VALUES (%s, %s)
    ON CONFLICT (element_id) DO NOTHING
"""

INSERT_MAPPING_SQL = """
    INSERT INTO bricklink_mappings (element_id, part_no, color_id, part_name, source)
    VALUES (%s, %s, %s, %s, 'rebrickable_reverse')
    ON CONFLICT (element_id) DO NOTHING
"""


def sticker_category_ids(cur) -> list[int]:
    cur.execute(FIND_STICKER_CATEGORIES_SQL, (STICKER_CATEGORY_NAME_PATTERNS,))
    return [r[0] for r in cur.fetchall()]


def resolve_one(cur, bl_part_no: str, dry_run: bool) -> tuple[str | None, int]:
    """Returns (matched rb_part_num or None, element rows created)."""
    rb_part_num = resolve_bl_part_no_reverse(bl_part_no, REBRICKABLE_API_KEY)
    time.sleep(INTER_CALL_DELAY)
    if not rb_part_num:
        return None, 0

    element_ids = resolve_part_colors_elements(rb_part_num, REBRICKABLE_API_KEY)
    time.sleep(INTER_CALL_DELAY)
    if not element_ids:
        return rb_part_num, 0

    created = 0
    for element_id in element_ids:
        info = resolve_element_via_rebrickable(element_id, REBRICKABLE_API_KEY)
        time.sleep(INTER_CALL_DELAY)
        if not info or info.get("bl_color_id") is None:
            continue
        # Attribute to the part_no we're resolving, not info["bl_part_no"] --
        # a Rebrickable part can list multiple BrickLink ids in
        # external_ids.BrickLink (e.g. sticker sheets covering several sets),
        # and resolve_element_via_rebrickable() only ever returns the first
        # one. rb_part_num was matched via bricklink_id=bl_part_no in the
        # first place, so this element genuinely belongs to bl_part_no
        # regardless of which BL id happens to be listed first upstream.
        if dry_run:
            print(f"    [dry-run] element_id={element_id} color_id={info['bl_color_id']} -> {bl_part_no}", flush=True)
            created += 1
            continue
        # bricklink_mappings.element_id FK's to lego_elements -- import_rebrickable.py
        # always inserts both together from the same elements.csv row; this
        # reverse-lookup path pulls element_ids live from Rebrickable's API
        # instead, which can include element_ids that were never in our local
        # elements.csv snapshot at all (confirmed live 2026-07-21: a real
        # ForeignKeyViolation on element_id 6002757, not present in
        # lego_elements). Same design_id-or-fallback-to-part_num rule as
        # import_rebrickable.py's own insert.
        design_id = info.get("design_id") or rb_part_num
        cur.execute(INSERT_ELEMENT_SQL, (element_id, design_id))
        cur.execute(INSERT_MAPPING_SQL, (element_id, bl_part_no, info["bl_color_id"], info.get("part_name")))
        if cur.rowcount > 0:
            created += 1
    return rb_part_num, created


def process_batch(cur, candidates: list[tuple[str, bool, bool]], dry_run: bool) -> dict:
    stats = {"resolved": 0, "unresolved": 0, "elements_created": 0, "plain_resolved": 0, "printed_resolved": 0, "low_priority_resolved": 0}
    for i, (bl_part_no, is_printed, is_low_priority) in enumerate(candidates):
        now = datetime.now(timezone.utc)
        rb_part_num, created = resolve_one(cur, bl_part_no, dry_run)
        tier = "printed" if is_printed else "plain"
        label = tier + ("+low-priority" if is_low_priority else "")

        if rb_part_num:
            stats["resolved"] += 1
            stats["elements_created"] += created
            stats[f"{tier}_resolved"] += 1
            if is_low_priority:
                stats["low_priority_resolved"] += 1
            print(f"  [{i + 1}/{len(candidates)}] {bl_part_no} ({label}) -> {rb_part_num}, {created} element(s)", flush=True)
            if not dry_run:
                cur.execute(UPSERT_FIX_SQL, (bl_part_no, rb_part_num, is_printed, is_low_priority, "reverse_lookup", created, now))
        else:
            stats["unresolved"] += 1
            print(f"  [{i + 1}/{len(candidates)}] {bl_part_no} ({label}) -> UNRESOLVED (retry-eligible)", flush=True)
            if not dry_run:
                cur.execute(UPSERT_FIX_SQL, (bl_part_no, None, is_printed, is_low_priority, "unresolved", 0, now))

        if not dry_run:
            cur.connection.commit()
    return stats


def send_report(stats: dict, remaining: dict[tuple[bool, bool], int], duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    mins, secs = divmod(int(duration_s), 60)
    total = stats["resolved"] + stats["unresolved"]
    # remaining is keyed (is_low_priority, is_printed) -> count
    remaining_plain = remaining.get((False, False), 0)
    remaining_printed = remaining.get((False, True), 0)
    remaining_low_priority = remaining.get((True, False), 0) + remaining.get((True, True), 0)
    subject = (f"[MOC Source] BL catalog reverse-map: {total} processed, "
               f"{remaining_plain:,} plain + {remaining_printed:,} printed + "
               f"{remaining_low_priority:,} low-priority remaining")
    body = (
        f"BrickLink catalog reverse-mapping run complete.\n\n"
        f"Resolved (plain parts)     : {stats['plain_resolved']}\n"
        f"Resolved (printed parts)   : {stats['printed_resolved']}\n"
        f"  of which low-priority    : {stats['low_priority_resolved']}\n"
        f"Unresolved (retry-eligible): {stats['unresolved']}\n"
        f"bricklink_mappings rows created: {stats['elements_created']}\n"
        f"Remaining -- plain parts        : {remaining_plain:,}\n"
        f"Remaining -- printed parts      : {remaining_printed:,}\n"
        f"Remaining -- low-priority (c-number/baseplate, either tier) : {remaining_low_priority:,}\n"
        f"Duration                   : {mins}m {secs}s\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = smtp_from
    msg["To"]      = report_email
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(smtp_from, [report_email], msg.as_string())
        print(f"Report emailed to {report_email}", flush=True)
    except Exception as e:
        print(f"Failed to send report email: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                         help=f"how many candidates to process this run (default {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--part-no", nargs="+", default=None,
                         help="process exactly these BrickLink part_nos, bypassing the resumable "
                              "priority query (also bypasses plain-vs-printed tiering)")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    if not REBRICKABLE_API_KEY:
        print("ERROR: REBRICKABLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    sticker_ids = sticker_category_ids(cur)

    if args.part_no:
        candidates = [(pn, False, False) for pn in args.part_no]
        print(f"Processing {len(candidates)} explicitly-specified part_no(s)")
    else:
        cur.execute(COUNT_SQL, {"sticker_ids": sticker_ids})
        remaining_before = {(low, printed): n for low, printed, n in cur.fetchall()}
        cur.execute(BATCH_SQL, {"sticker_ids": sticker_ids, "limit": args.batch_size})
        candidates = cur.fetchall()
        low_priority_total = remaining_before.get((True, False), 0) + remaining_before.get((True, True), 0)
        print(f"{remaining_before.get((False, False), 0):,} plain + {remaining_before.get((False, True), 0):,} printed + "
              f"{low_priority_total:,} low-priority (c-number/baseplate) retry-eligible total; "
              f"selected {len(candidates)} for this run "
              f"(priority: plain, then printed, then low-priority last)")

    if not candidates:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    stats = process_batch(cur, candidates, args.dry_run)

    cur.execute(COUNT_SQL, {"sticker_ids": sticker_ids})
    remaining_after = {(low, printed): n for low, printed, n in cur.fetchall()}

    cur.close()
    conn.close()

    low_priority_remaining = remaining_after.get((True, False), 0) + remaining_after.get((True, True), 0)
    print(f"\nDone. Resolved: {stats['resolved']} ({stats['plain_resolved']} plain, "
          f"{stats['printed_resolved']} printed, {stats['low_priority_resolved']} of which low-priority), "
          f"unresolved: {stats['unresolved']}, "
          f"{stats['elements_created']} bricklink_mappings row(s) created.")
    print(f"  Remaining: {remaining_after.get((False, False), 0):,} plain, "
          f"{remaining_after.get((False, True), 0):,} printed, "
          f"{low_priority_remaining:,} low-priority")

    if not args.dry_run:
        duration_s = time.monotonic() - start_time
        send_report(stats, remaining_after, duration_s)


if __name__ == "__main__":
    main()
