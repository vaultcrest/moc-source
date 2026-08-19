#!/usr/bin/env python3
"""Full sweep: live BrickLink inventory + sold Price Guide for every
minifig in brickstore_minifig_catalog.

For each minifig, 3 BL calls: fetch_minifig_parts() (part-level inventory,
native BL part_no/color_id, no Rebrickable translation) and
fetch_minifig_price_guide() for New and Used. Confirmed live 2026-08-18
against aqu001/hp637 that both endpoints return real data directly per
minifig -- see scripts/_bricklink_lookup.py's BLClient methods.

Inventory: minifig_inventory_items is fully delete+reinserted per minifig
each scan (own rows only, matches the per-source-scopes-its-own-write
convention used elsewhere, e.g. bricklink_alternates). Separate from
brickstore_minifig_inventory_items (bulk BrickStore export, reference
table, untouched by this script).

Price: same month/region bucketing + outlier-filtering pipeline as
scrape_bl_price_guide.py (scripts/_price_guide_regions.py,
scripts/_outlier_filter.py, reused unchanged) into
bl_minifig_price_guide_monthly, an exact column mirror of
bl_price_guide_monthly keyed by minifig_no instead of (part_no, color_id).
Same RETENTION_MONTHS floor -- BrickLink's price_detail[] is only
dense/reliable for the most recent ~6 full calendar months.

Resumable via brickstore_minifig_catalog.bl_inventory_imported_at /
bl_price_scanned_at (no separate scan_log table -- mirrors the existing
inventory_imported_at/rb_inventory_imported_at markers already on that
table). A minifig counts as done once all 3 calls were attempted
(reached BrickLink, even if the response was empty/404) -- same
scanned-not-necessarily-found semantics as bl_price_guide_scan_log.

Deployed at --batch-size 1666 (x3 calls = 4,998/night) for the nightly
timer, in the slot vacated by pausing scrape_bl_price_guide.py
(2026-08-18, see CHANGELOG) to free budget for this and the still-queued
minifig mapping crawl.

Emails a per-run summary via SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/
SMTP_FROM/REPORT_EMAIL, same convention as scrape_bl_price_guide.py.
No-ops if SMTP_HOST or REPORT_EMAIL aren't set. Skipped entirely in
--dry-run.

Usage:
    DATABASE_URL=... python scripts/scrape_bl_minifig_data.py [--batch-size 500]
    DATABASE_URL=... python scripts/scrape_bl_minifig_data.py --minifig-no aqu001 [--dry-run]
"""
import argparse
import os
import smtplib
import statistics
import sys
import time
from datetime import date, datetime, timezone
from email.mime.text import MIMEText

import psycopg2
import psycopg2.extras
from _bricklink_lookup import BLClient
from _outlier_filter import _to_cents, bucket_by_month, compute_stats, filter_bucket, month_floor_minus
from _price_guide_regions import rows_by_region
from dotenv import load_dotenv

load_dotenv()

BRICKLINK_CONSUMER_KEY = os.environ.get("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.environ.get("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.environ.get("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.environ.get("BRICKLINK_TOKEN_SECRET", "")

bl_client = BLClient(BRICKLINK_CONSUMER_KEY, BRICKLINK_CONSUMER_SECRET, BRICKLINK_TOKEN, BRICKLINK_TOKEN_SECRET)

RETENTION_MONTHS = 6  # same reasoning as scrape_bl_price_guide.py -- older data is sporadic, not real history

INTER_CALL_DELAY = 1.0
DEFAULT_BATCH_SIZE = 1666  # x3 calls/minifig = 4,998/night, just under the ~5,000/day ceiling
MAX_CONSECUTIVE_FAILURES = 5

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BATCH_SQL = """
    SELECT minifig_no FROM brickstore_minifig_catalog
    WHERE bl_price_scanned_at IS NULL
    ORDER BY minifig_no
    LIMIT %(limit)s
"""

COUNT_SQL = "SELECT count(*) FROM brickstore_minifig_catalog WHERE bl_price_scanned_at IS NULL"

DELETE_INVENTORY_SQL = "DELETE FROM minifig_inventory_items WHERE minifig_no = %s"

INSERT_INVENTORY_SQL = """
    INSERT INTO minifig_inventory_items
        (minifig_no, part_no, color_id, quantity, extra_quantity, is_alternate, is_counterpart, match_no)
    VALUES %s
"""

UPSERT_MONTHLY_SQL = """
    INSERT INTO bl_minifig_price_guide_monthly
        (minifig_no, region, new_or_used, month,
         avg_price_cents, min_price_cents, max_price_cents, median_price_cents,
         sample_count, raw_sample_count, updated_at)
    VALUES (%(minifig_no)s, %(region)s, %(new_or_used)s, %(month)s,
            %(avg_price_cents)s, %(min_price_cents)s, %(max_price_cents)s, %(median_price_cents)s,
            %(sample_count)s, %(raw_sample_count)s, %(updated_at)s)
    ON CONFLICT (minifig_no, region, new_or_used, month) DO UPDATE SET
        avg_price_cents = EXCLUDED.avg_price_cents,
        min_price_cents = EXCLUDED.min_price_cents,
        max_price_cents = EXCLUDED.max_price_cents,
        median_price_cents = EXCLUDED.median_price_cents,
        sample_count = EXCLUDED.sample_count,
        raw_sample_count = EXCLUDED.raw_sample_count,
        updated_at = EXCLUDED.updated_at
"""

MARK_DONE_SQL = """
    UPDATE brickstore_minifig_catalog
    SET bl_inventory_imported_at = %(now)s, bl_price_scanned_at = %(now)s
    WHERE minifig_no = %(minifig_no)s
"""


def process_minifig(cur, minifig_no: str, now: datetime, cutoff_month: date, dry_run: bool) -> dict:
    attempted, parts = bl_client.fetch_minifig_parts(minifig_no)
    if not attempted:
        return {"status": "skipped_transient"}
    time.sleep(INTER_CALL_DELAY)

    if dry_run:
        print(f"    [dry-run] inventory: {len(parts)} part row(s)")
    else:
        cur.execute(DELETE_INVENTORY_SQL, (minifig_no,))
        if parts:
            rows = [
                (minifig_no, p["part_no"], p["color_id"], p["quantity"], p["extra_quantity"],
                 p["is_alternate"], p["is_counterpart"], p["match_no"])
                for p in parts
            ]
            psycopg2.extras.execute_values(cur, INSERT_INVENTORY_SQL, rows)

    responses = {}
    for j, new_or_used in enumerate(("N", "U")):
        attempted, data = bl_client.fetch_minifig_price_guide(minifig_no, new_or_used)
        if not attempted:
            return {"status": "skipped_transient"}
        responses[new_or_used] = data
        time.sleep(INTER_CALL_DELAY)

    month_rows = 0
    errors = []
    for new_or_used, data in responses.items():
        price_detail = (data or {}).get("price_detail") or []
        if not price_detail:
            continue
        for month, month_all_rows in bucket_by_month(price_detail).items():
            if month < cutoff_month:
                continue
            for region, rows in rows_by_region(month_all_rows).items():
                if not rows:
                    continue
                try:
                    filtered = filter_bucket(rows, None)
                    stats = compute_stats(filtered)
                except Exception as e:
                    error = {"minifig_no": minifig_no, "new_or_used": new_or_used,
                              "month": month, "region": region, "error": f"{type(e).__name__}: {e}"}
                    errors.append(error)
                    print(f"    ERROR {minifig_no}/{new_or_used}/{region} {month}: "
                          f"{type(e).__name__}: {e} -- skipping this bucket", file=sys.stderr, flush=True)
                    continue
                if dry_run:
                    print(f"    [dry-run] {new_or_used}/{region} {month}: "
                          f"n={stats['sample_count']}/{len(rows)} avg={stats['avg_price_cents']}")
                else:
                    cur.execute(UPSERT_MONTHLY_SQL, {
                        "minifig_no": minifig_no, "region": region,
                        "new_or_used": new_or_used, "month": month,
                        "raw_sample_count": len(rows), "updated_at": now,
                        **stats,
                    })
                month_rows += 1

    if not dry_run:
        cur.execute(MARK_DONE_SQL, {"now": now, "minifig_no": minifig_no})

    return {"status": "processed", "inventory_rows": len(parts), "month_rows": month_rows, "errors": errors}


def send_report(stats: dict, remaining_after: int, duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    processed = stats["processed"]
    errors = stats.get("errors", [])
    mins, secs = divmod(int(duration_s), 60)
    error_suffix = f" ({len(errors)} errors)" if errors else ""
    error_section = ""
    if errors:
        error_section = "\nErrors this run (bucket skipped, needs review):\n" + "\n".join(
            f"  {e['minifig_no']}/{e['new_or_used']}/{e['region']} {e['month']}: {e['error']}"
            for e in errors
        ) + "\n"

    if remaining_after == 0:
        subject = f"[MOC Source] BL minifig inventory+price sweep COMPLETE{error_suffix}"
        body = (
            "The BrickLink minifig inventory+price sweep has finished -- every "
            "known minifig now has bl_price_scanned_at set.\n\n"
            f"This run   : processed {processed}, skipped (transient) {stats['skipped_transient']}\n"
            f"Inventory rows written : {stats['inventory_rows']}\n"
            f"Month-rows written     : {stats['month_rows']}\n"
            f"Duration   : {mins}m {secs}s\n"
            f"{error_section}\n"
            "Nightly runs will keep firing but will find nothing left to do until "
            "new minifigs are added to brickstore_minifig_catalog.\n"
        )
    else:
        subject = f"[MOC Source] BL minifig data: {processed} processed, {remaining_after:,} remaining{error_suffix}"
        body = (
            "Nightly BL minifig inventory+price scrape run complete.\n\n"
            f"Processed              : {processed}\n"
            f"Skipped (transient)    : {stats['skipped_transient']}\n"
            f"Inventory rows written : {stats['inventory_rows']}\n"
            f"Month-rows written     : {stats['month_rows']}\n"
            f"Remaining after this run: {remaining_after:,}\n"
            f"Duration   : {mins}m {secs}s\n"
            f"{error_section}"
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
                         help=f"how many minifigs to process this run (default {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--minifig-no", default=None, help="process exactly this minifig_no, bypassing the batch query")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.minifig_no:
        minifig_nos = [args.minifig_no]
        print("Processing 1 explicitly-specified minifig")
    else:
        cur.execute(COUNT_SQL)
        remaining = cur.fetchone()[0]
        cur.execute(BATCH_SQL, {"limit": args.batch_size})
        minifig_nos = [r[0] for r in cur.fetchall()]
        print(f"{remaining} unscanned minifig(s) total; selected {len(minifig_nos)} for this run")

    if not minifig_nos:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    stats = {"processed": 0, "skipped_transient": 0, "inventory_rows": 0, "month_rows": 0, "errors": []}
    consecutive_failures = 0
    now = datetime.now(timezone.utc)
    cutoff_month = month_floor_minus(now, RETENTION_MONTHS)
    print(f"Retention floor: keeping month >= {cutoff_month} ({RETENTION_MONTHS} full months back)")

    for i, minifig_no in enumerate(minifig_nos):
        result = process_minifig(cur, minifig_no, now, cutoff_month, args.dry_run)
        if result["status"] == "skipped_transient":
            stats["skipped_transient"] += 1
            consecutive_failures += 1
            print(f"[{i + 1}/{len(minifig_nos)}] {minifig_no}: skipped (transient failure)", flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"{MAX_CONSECUTIVE_FAILURES} consecutive transient failures — aborting batch early",
                      file=sys.stderr)
                break
        else:
            consecutive_failures = 0
            if not args.dry_run:
                conn.commit()
            stats["processed"] += 1
            stats["inventory_rows"] += result["inventory_rows"]
            stats["month_rows"] += result["month_rows"]
            stats["errors"].extend(result.get("errors", []))
            err_suffix = f", {len(result['errors'])} error(s)" if result.get("errors") else ""
            print(f"[{i + 1}/{len(minifig_nos)}] {minifig_no}: processed "
                  f"({result['inventory_rows']} part(s), {result['month_rows']} month-rows{err_suffix})", flush=True)

    cur.execute(COUNT_SQL)
    remaining_after = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\nDone. Processed {stats['processed']}, skipped (transient) {stats['skipped_transient']}.")
    if stats["processed"]:
        print(f"  Inventory rows written : {stats['inventory_rows']}")
        print(f"  Month-rows written     : {stats['month_rows']}")
    if stats["errors"]:
        print(f"  Errors (skipped)       : {len(stats['errors'])}")
    print(f"  Remaining              : {remaining_after:,}")

    if not args.dry_run:
        duration_s = time.monotonic() - start_time
        send_report(stats, remaining_after, duration_s)


if __name__ == "__main__":
    main()
