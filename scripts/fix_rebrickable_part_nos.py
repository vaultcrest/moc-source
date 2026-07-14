#!/usr/bin/env python3
"""One-time correction pass for bricklink_mappings.part_no rows written with
Rebrickable's own print-variant numbering (e.g. "27372pr0006") instead of a
real BrickLink part number (e.g. "27372pb06").

Root cause (found + fixed 2026-07-14): three independent write paths each
read the wrong field out of Rebrickable's API/CSV data. This script repairs
the ~29,689 rows already written before those fixes landed.

Two-tier resolution per distinct bad part_no:
  1. Bulk lookup via Rebrickable's /lego/parts/?part_nums=... (cheap, most
     rows resolve here).
  2. For anything the bulk call misses, fall back to a per-element_id lookup
     via /lego/elements/{id}/ -- Rebrickable sometimes renumbers/consolidates
     print variants, so a stored part_no string can go stale even though the
     underlying element still resolves fine through its stable element_id.

A part_no that fails BOTH tiers is recorded as 'unresolved' in
rebrickable_part_no_fixes, NOT treated as permanently done -- Rebrickable's
own data changes over time, so unresolved rows stay retry-eligible on a
future run (just deprioritized behind never-attempted rows). Resolved rows
update every bricklink_mappings row sharing that old part_no, and clean up
now-orphaned bl_part_catalog / bricklink_alternates rows keyed on the old
(404-junk) value.

Rate limiting: Rebrickable's rules are ~1 req/sec average with 429 retry
honoring Retry-After (see scripts/_rebrickable_lookup.py). Confirmed via live
testing 2026-07-14: 1.2s pacing holds clean, bulk calls cap at 100 part_nums
each (larger requests silently truncate results). No daily quota is known
for Rebrickable (unlike BrickLink's ~5,000/day), so this is designed to run
as a single supervised pass over the whole backlog, not spread across nights
-- but is resumable via --batch-size if you'd rather run it in chunks.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/fix_rebrickable_part_nos.py [--batch-size N] [--dry-run]
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/fix_rebrickable_part_nos.py --part-no 27372pr0006 [--dry-run]
"""
import argparse
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg2
import psycopg2.extras
from _rebrickable_lookup import (
    MAX_PART_NUMS_PER_CALL,
    resolve_bl_part_nos_bulk,
    resolve_element_via_rebrickable,
)
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
INTER_CALL_DELAY = 1.2
DEFAULT_BATCH_SIZE = 30000  # effectively "the whole backlog" in one run; override with --batch-size to chunk it

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BAD_PART_NO_PATTERN = r"pr[0-9]+$"

BATCH_SQL = f"""
    SELECT dp.part_no
    FROM (SELECT DISTINCT part_no FROM bricklink_mappings WHERE part_no ~ '{BAD_PART_NO_PATTERN}') dp
    LEFT JOIN rebrickable_part_no_fixes f ON f.old_part_no = dp.part_no
    WHERE f.old_part_no IS NULL OR f.method = 'unresolved'
    ORDER BY f.attempted_at ASC NULLS FIRST, dp.part_no
    LIMIT %s
"""

COUNT_SQL = f"""
    SELECT count(DISTINCT bm.part_no)
    FROM bricklink_mappings bm
    LEFT JOIN rebrickable_part_no_fixes f ON f.old_part_no = bm.part_no
    WHERE bm.part_no ~ '{BAD_PART_NO_PATTERN}'
      AND (f.old_part_no IS NULL OR f.method = 'unresolved')
"""

UPSERT_FIX_SQL = """
    INSERT INTO rebrickable_part_no_fixes (old_part_no, new_part_no, method, attempted_at)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (old_part_no) DO UPDATE SET
        new_part_no = EXCLUDED.new_part_no,
        method = EXCLUDED.method,
        attempted_at = EXCLUDED.attempted_at
"""


def element_ids_for_part_no(cur, part_no: str) -> list[int]:
    cur.execute("SELECT element_id FROM bricklink_mappings WHERE part_no = %s", (part_no,))
    return [r[0] for r in cur.fetchall()]


def apply_correction(cur, old_part_no: str, new_part_no: str) -> None:
    cur.execute(
        "UPDATE bricklink_mappings SET part_no = %s, source = 'rebrickable_corrected' WHERE part_no = %s",
        (new_part_no, old_part_no),
    )
    # Clean up 404-junk rows the mold-backfill script left behind for the old,
    # untranslatable value -- otherwise they'd sit orphaned forever.
    cur.execute("DELETE FROM bl_part_catalog WHERE part_no = %s", (old_part_no,))
    cur.execute("DELETE FROM bricklink_alternates WHERE part_no = %s", (old_part_no,))


def process_batch(cur, old_part_nos: list[str], dry_run: bool) -> dict:
    """Processes old_part_nos in sub-chunks of MAX_PART_NUMS_PER_CALL rather than
    one giant bulk lookup up front -- so output and DB commits land continuously
    (every ~100 part_nos) instead of going silent for the whole run before the
    first line of progress appears."""
    stats = {"bulk": 0, "element_fallback": 0, "unresolved": 0}

    for chunk_start in range(0, len(old_part_nos), MAX_PART_NUMS_PER_CALL):
        chunk = old_part_nos[chunk_start:chunk_start + MAX_PART_NUMS_PER_CALL]
        chunk_num = chunk_start // MAX_PART_NUMS_PER_CALL + 1
        total_chunks = (len(old_part_nos) + MAX_PART_NUMS_PER_CALL - 1) // MAX_PART_NUMS_PER_CALL
        print(f"--- chunk {chunk_num}/{total_chunks} ({len(chunk)} part_nos) ---", flush=True)

        now = datetime.now(timezone.utc)
        bulk_resolved = resolve_bl_part_nos_bulk(chunk, REBRICKABLE_API_KEY)
        if chunk_start + MAX_PART_NUMS_PER_CALL < len(old_part_nos):
            time.sleep(INTER_CALL_DELAY)

        for old_part_no in chunk:
            new_part_no = bulk_resolved.get(old_part_no)
            method = "bulk" if new_part_no else None

            if not new_part_no:
                for element_id in element_ids_for_part_no(cur, old_part_no):
                    info = resolve_element_via_rebrickable(element_id, REBRICKABLE_API_KEY)
                    time.sleep(INTER_CALL_DELAY)
                    if info and info["bl_part_no"]:
                        new_part_no = info["bl_part_no"]
                        method = "element_fallback"
                        break

            if new_part_no:
                stats[method] += 1
                print(f"  {old_part_no} -> {new_part_no} ({method})", flush=True)
                if not dry_run:
                    apply_correction(cur, old_part_no, new_part_no)
                    cur.execute(UPSERT_FIX_SQL, (old_part_no, new_part_no, method, now))
            else:
                stats["unresolved"] += 1
                print(f"  {old_part_no} -> UNRESOLVED (retry-eligible)", flush=True)
                if not dry_run:
                    cur.execute(UPSERT_FIX_SQL, (old_part_no, None, "unresolved", now))

            if not dry_run:
                cur.connection.commit()

    return stats


def send_report(stats: dict, remaining_after: int, duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    mins, secs = divmod(int(duration_s), 60)
    total = stats["bulk"] + stats["element_fallback"] + stats["unresolved"]
    subject = f"[MOC Source] Rebrickable part_no correction: {total} processed, {remaining_after:,} remaining"
    body = (
        "Rebrickable part_no correction run complete.\n\n"
        f"Resolved via bulk lookup     : {stats['bulk']}\n"
        f"Resolved via element fallback: {stats['element_fallback']}\n"
        f"Unresolved (retry-eligible)  : {stats['unresolved']}\n"
        f"Remaining after this run     : {remaining_after:,}\n"
        f"Duration                     : {mins}m {secs}s\n"
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
                         help=f"how many distinct bad part_nos to process this run (default {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--part-no", nargs="+", default=None,
                         help="process exactly these part_nos, bypassing the resumable batch query")
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

    if args.part_no:
        old_part_nos = args.part_no
        print(f"Processing {len(old_part_nos)} explicitly-specified part_no(s)")
    else:
        cur.execute(COUNT_SQL)
        remaining = cur.fetchone()[0]
        cur.execute(BATCH_SQL, (args.batch_size,))
        old_part_nos = [r[0] for r in cur.fetchall()]
        print(f"{remaining} unresolved bad part_no(s) total; selected {len(old_part_nos)} for this run")

    if not old_part_nos:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    stats = process_batch(cur, old_part_nos, args.dry_run)

    cur.execute(COUNT_SQL)
    remaining_after = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\nDone. Resolved via bulk: {stats['bulk']}, via element fallback: {stats['element_fallback']}, "
          f"unresolved: {stats['unresolved']}.")
    print(f"  Remaining: {remaining_after:,}")

    if not args.dry_run:
        duration_s = time.monotonic() - start_time
        send_report(stats, remaining_after, duration_s)


if __name__ == "__main__":
    main()
