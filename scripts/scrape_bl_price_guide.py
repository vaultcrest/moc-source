#!/usr/bin/env python3
"""Priority-ordered first pass: BrickLink Price Guide, worldwide, monthly history,
bucketed into global/north_america/eu_gb/other.

For every (part_no, color_id) pair in bricklink_mappings, fetches BrickLink's
worldwide sold-listing Price Guide (New and Used, 2 calls/pair -- confirmed
live 2026-07-15 that omitting BrickLink's region param returns the same
single call's worth of data, unfiltered, rather than costing extra calls)
and buckets each response's price_detail[] by month(date_ordered). A single
call can return rows going back years, but only the most recent
RETENTION_MONTHS (6) full calendar months are dense/reliable -- older than
that BrickLink's data is sporadic leftover single sales, not real history
(confirmed live 2026-07-15) -- so anything older than the month_floor_minus()
cutoff is dropped before it ever reaches bl_price_guide_monthly. Within each
kept month, rows are further split into 4 region groups
(scripts/_price_guide_regions.py: global/north_america/eu_gb/other) by
seller_country_code. Each (month, region) group is independently
outlier-filtered (scripts/_outlier_filter.py's three-tier MAD / PAB-ratio /
max-drop strategy) before avg/min/max/median are computed and upserted into
bl_price_guide_monthly -- 4 rows per (pair, kept month) instead of 1. Raw
price_detail rows are never persisted -- only the derived monthly summary.

Priority order (this is a one-time first pass, not a recurring cadence
split): pairs with an active PAB/BAP price first, then everything else by
bl_part_catalog.last_used_year descending (current year backward), then
pairs with no year data at all, last.

Resumable via bl_price_guide_scan_log (a thin tracker separate from
bl_price_guide_monthly itself, so a pair with zero BL sales -- which
produces no monthly rows at all -- still gets marked done instead of being
retried every run). One scan covers all 4 regions at once (single worldwide
fetch), so scan_log tracks by (part_no, color_id) only -- no region column.

Deployed at --batch-size 2500 (5,000 calls/night) for the nightly timer --
originally sharing BrickLink's ~5,000 calls/day budget with
scrape_bl_mold_data.py (throttled to 500/night, 2026-07-15), but that script
was retired 2026-07-16 (replaced by scripts/ingest_brickstore_catalog.py,
which needs zero BrickLink API calls). Bumped from 2,250 to 2,500 pairs on
2026-07-16 to use the freed 250-pair/500-call headroom, landing at the full
~5,000/day budget -- an unwritten BrickLink limit, not a documented hard
cap, so this is treated as the ceiling rather than pushed further.

Emails a per-run summary (or, once the first pass has nothing left, a
distinct completion notice) via SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/
SMTP_FROM/REPORT_EMAIL, same convention as scrape_bl_mold_data.py. No-ops if
SMTP_HOST or REPORT_EMAIL aren't set. Skipped entirely in --dry-run.

Usage:
    DATABASE_URL=... python scripts/scrape_bl_price_guide.py [--batch-size 500]
    DATABASE_URL=... python scripts/scrape_bl_price_guide.py --part-no 3684a --color-id 5 [--dry-run]
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

# BrickLink's price_detail[] isn't a clean rolling window -- the last ~6-7
# months are dense/comprehensive (hundreds of sales/month for common parts),
# but older than that it's sporadic leftover single listings, not real
# history (confirmed live 2026-07-15: part 2357/Black had 962 sales in one
# recent month vs. 1-3/month scattered back to 2018, with whole months like
# Dec 2025 missing entirely). Floor everything older than RETENTION_MONTHS
# full months back so bl_price_guide_monthly never gets polluted with those
# single-anecdote months. Month-aligned via month_floor_minus(), not a naive
# day-precise `now - N*30 days` (which would land mid-month and truncate the
# oldest kept month to its second half only).
RETENTION_MONTHS = 6

INTER_CALL_DELAY = 1.0  # polite pacing, matches scrape_bl_mold_data.py's convention
DEFAULT_BATCH_SIZE = 500
MAX_CONSECUTIVE_FAILURES = 5

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BASE_WHERE = """
    bm.part_no IS NOT NULL AND bm.color_id IS NOT NULL
    AND bm.part_no !~ 'pr[0-9]+$'
    AND NOT EXISTS (
      SELECT 1 FROM bl_price_guide_scan_log sl
      WHERE sl.part_no = bm.part_no AND sl.color_id = bm.color_id
    )
"""

BATCH_SQL = f"""
    SELECT DISTINCT bm.part_no, bm.color_id,
           EXISTS (
             SELECT 1 FROM lego_element_prices lep
             WHERE lep.element_id = bm.element_id AND lep.channel IN ('pab','bap')
           ) AS has_pab,
           bpc.last_used_year
    FROM bricklink_mappings bm
    LEFT JOIN bl_part_catalog bpc ON bpc.part_no = bm.part_no
    WHERE {BASE_WHERE}
    ORDER BY has_pab DESC, bpc.last_used_year DESC NULLS LAST
    LIMIT %(limit)s
"""

COUNT_SQL = f"""
    SELECT count(*) FROM (
        SELECT DISTINCT bm.part_no, bm.color_id
        FROM bricklink_mappings bm
        LEFT JOIN bl_part_catalog bpc ON bpc.part_no = bm.part_no
        WHERE {BASE_WHERE}
    ) x
"""

PAB_PRICE_SQL = """
    SELECT lep.price_cents
    FROM lego_element_prices lep
    JOIN bricklink_mappings bm ON bm.element_id = lep.element_id
    WHERE bm.part_no = %s AND bm.color_id = %s
      AND lep.channel IN ('pab', 'bap') AND lep.price_cents IS NOT NULL
    LIMIT 1
"""

UPSERT_MONTHLY_SQL = """
    INSERT INTO bl_price_guide_monthly
        (part_no, color_id, region, new_or_used, month,
         avg_price_cents, min_price_cents, max_price_cents, median_price_cents,
         sample_count, raw_sample_count, updated_at)
    VALUES (%(part_no)s, %(color_id)s, %(region)s, %(new_or_used)s, %(month)s,
            %(avg_price_cents)s, %(min_price_cents)s, %(max_price_cents)s, %(median_price_cents)s,
            %(sample_count)s, %(raw_sample_count)s, %(updated_at)s)
    ON CONFLICT (part_no, color_id, region, new_or_used, month) DO UPDATE SET
        avg_price_cents = EXCLUDED.avg_price_cents,
        min_price_cents = EXCLUDED.min_price_cents,
        max_price_cents = EXCLUDED.max_price_cents,
        median_price_cents = EXCLUDED.median_price_cents,
        sample_count = EXCLUDED.sample_count,
        raw_sample_count = EXCLUDED.raw_sample_count,
        updated_at = EXCLUDED.updated_at
"""

UPSERT_SCAN_LOG_SQL = """
    INSERT INTO bl_price_guide_scan_log (part_no, color_id, scanned_at)
    VALUES (%s, %s, %s)
    ON CONFLICT (part_no, color_id) DO UPDATE SET scanned_at = EXCLUDED.scanned_at
"""

UPSERT_VELOCITY_SQL = """
    INSERT INTO bl_price_guide_velocity (part_no, color_id, region, new_or_used, avg_monthly_qty, price_cv, updated_at)
    VALUES (%(part_no)s, %(color_id)s, %(region)s, %(new_or_used)s, %(avg_monthly_qty)s, %(price_cv)s, %(updated_at)s)
    ON CONFLICT (part_no, color_id, region, new_or_used) DO UPDATE SET
        avg_monthly_qty = EXCLUDED.avg_monthly_qty,
        price_cv = EXCLUDED.price_cv,
        updated_at = EXCLUDED.updated_at
"""


def _pab_price_cents(cur, part_no: str, color_id: int) -> int | None:
    cur.execute(PAB_PRICE_SQL, (part_no, color_id))
    row = cur.fetchone()
    return row[0] if row else None


def process_pair(cur, part_no: str, color_id: int, now: datetime, cutoff_month: date, dry_run: bool) -> dict:
    pab_price_cents = _pab_price_cents(cur, part_no, color_id)

    responses = {}
    for j, new_or_used in enumerate(("N", "U")):
        attempted, data = bl_client.fetch_price_guide(part_no, color_id, new_or_used)
        if not attempted:
            return {"status": "skipped_transient"}
        responses[new_or_used] = data
        if j == 0:
            time.sleep(INTER_CALL_DELAY)

    month_rows = 0
    errors = []
    volume_by_key: dict[tuple[str, str], list[int]] = {}  # (region, new_or_used) -> [qty_sold per month]
    prices_by_key: dict[tuple[str, str], list[int]] = {}  # (region, new_or_used) -> pooled filtered unit_price cents, all kept months
    for new_or_used, data in responses.items():
        price_detail = (data or {}).get("price_detail") or []
        if not price_detail:
            continue
        for month, month_all_rows in bucket_by_month(price_detail).items():
            if month < cutoff_month:
                continue  # sporadic leftover single sales beyond BL's real ~6-month window, not real history
            # 'global' is the whole month_all_rows set, not a peer of the
            # other three -- north_america/eu_gb/other mutually exclusively
            # partition it. Each of the 4 gets its own outlier-filter pass
            # and its own bl_price_guide_monthly row.
            for region, rows in rows_by_region(month_all_rows).items():
                if not rows:
                    continue
                try:
                    filtered = filter_bucket(rows, pab_price_cents)
                    stats = compute_stats(filtered)
                except Exception as e:
                    error = {"part_no": part_no, "color_id": color_id, "new_or_used": new_or_used,
                              "month": month, "region": region, "error": f"{type(e).__name__}: {e}"}
                    errors.append(error)
                    print(f"    ERROR {part_no}/{color_id}/{new_or_used}/{region} {month}: "
                          f"{type(e).__name__}: {e} -- skipping this bucket", file=sys.stderr, flush=True)
                    continue
                if dry_run:
                    print(f"    [dry-run] {part_no}/{color_id}/{new_or_used}/{region} {month}: "
                          f"n={stats['sample_count']}/{len(rows)} avg={stats['avg_price_cents']}")
                else:
                    cur.execute(UPSERT_MONTHLY_SQL, {
                        "part_no": part_no, "color_id": color_id, "region": region,
                        "new_or_used": new_or_used, "month": month,
                        "raw_sample_count": len(rows), "updated_at": now,
                        **stats,
                    })
                month_rows += 1
                # Sum actual units sold (quantity), not sale-event count, from the
                # outlier-filtered rows -- a raw sum would double-count the same
                # kind of bogus bulk "sale" (e.g. 129 units at $0.00, confirmed
                # 2026-07-15) that the price outlier filter already exists to reject.
                qty_sold = sum(int(row.get("quantity", 1)) for row in filtered)
                volume_by_key.setdefault((region, new_or_used), []).append(qty_sold)
                prices_by_key.setdefault((region, new_or_used), []).extend(
                    _to_cents(row["unit_price"]) for row in filtered
                )

    if not dry_run:
        cur.execute(UPSERT_SCAN_LOG_SQL, (part_no, color_id, now))
        for (region, new_or_used), monthly_counts in volume_by_key.items():
            avg_monthly_qty = sum(monthly_counts) / len(monthly_counts)
            prices = prices_by_key.get((region, new_or_used), [])
            mean_price = statistics.fmean(prices) if prices else None
            # Population stdev of the pooled per-sale prices this call returned
            # (up to ~6 months at once), not stddev-of-monthly-averages -- that
            # would only show drift between month-to-month averages and miss
            # real intra-month price spread. Refreshed each run like
            # avg_monthly_qty, not tracked as its own trend over time.
            price_cv = (statistics.pstdev(prices) / mean_price) if mean_price else None
            cur.execute(UPSERT_VELOCITY_SQL, {
                "part_no": part_no, "color_id": color_id, "region": region,
                "new_or_used": new_or_used, "avg_monthly_qty": avg_monthly_qty,
                "price_cv": price_cv, "updated_at": now,
            })

    return {"status": "processed", "month_rows": month_rows, "errors": errors}


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
    tier_line = (f"  PAB/BAP-priced pairs : {stats['has_pab']}/{processed}\n"
                 f"  Month-rows written   : {stats['month_rows']}\n") if processed else ""
    error_suffix = f" ({len(errors)} errors)" if errors else ""
    error_section = ""
    if errors:
        error_section = "\nErrors this run (bucket skipped, needs review):\n" + "\n".join(
            f"  {e['part_no']}/{e['color_id']}/{e['new_or_used']}/{e['region']} {e['month']}: {e['error']}"
            for e in errors
        ) + "\n"

    if remaining_after == 0:
        subject = f"[MOC Source] BL price guide first pass COMPLETE{error_suffix}"
        body = (
            "The BrickLink Price Guide first pass (worldwide, New+Used, bucketed "
            "into global/North America/EU+UK/other, priority-ordered) has finished "
            "-- every known (part_no, color_id) pair now has a scan_log entry.\n\n"
            f"This run   : processed {processed}, skipped (transient) {stats['skipped_transient']}\n"
            f"{tier_line}"
            f"Duration   : {mins}m {secs}s\n"
            f"{error_section}\n"
            "Nightly runs will keep firing but will find nothing left to do until "
            "new pairs are added to bricklink_mappings.\n"
        )
    else:
        subject = f"[MOC Source] BL price guide: {processed} processed, {remaining_after:,} remaining{error_suffix}"
        body = (
            "Nightly BL Price Guide scrape run complete.\n\n"
            f"Processed            : {processed}\n"
            f"Skipped (transient)  : {stats['skipped_transient']}\n"
            f"{tier_line}"
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
                         help=f"how many (part_no, color_id) pairs to process this run (default {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--part-no", default=None, help="process exactly this part_no, bypassing the batch query")
    parser.add_argument("--color-id", type=int, default=None, help="paired with --part-no")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()
    if args.part_no and args.color_id is None:
        parser.error("--part-no requires --color-id")

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.part_no:
        pairs = [(args.part_no, args.color_id, None)]
        print(f"Processing 1 explicitly-specified pair")
    else:
        cur.execute(COUNT_SQL)
        remaining = cur.fetchone()[0]
        cur.execute(BATCH_SQL, {"limit": args.batch_size})
        pairs = [(r[0], r[1], r[2]) for r in cur.fetchall()]
        print(f"{remaining} unscanned pair(s) total; selected {len(pairs)} for this run")

    if not pairs:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    stats = {"processed": 0, "skipped_transient": 0, "has_pab": 0, "month_rows": 0, "errors": []}
    consecutive_failures = 0
    now = datetime.now(timezone.utc)
    cutoff_month = month_floor_minus(now, RETENTION_MONTHS)
    print(f"Retention floor: keeping month >= {cutoff_month} ({RETENTION_MONTHS} full months back)")

    for i, (part_no, color_id, has_pab) in enumerate(pairs):
        result = process_pair(cur, part_no, color_id, now, cutoff_month, args.dry_run)
        if result["status"] == "skipped_transient":
            stats["skipped_transient"] += 1
            consecutive_failures += 1
            print(f"[{i + 1}/{len(pairs)}] {part_no}/{color_id}: skipped (transient failure)", flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"{MAX_CONSECUTIVE_FAILURES} consecutive transient failures — aborting batch early",
                      file=sys.stderr)
                break
        else:
            consecutive_failures = 0
            if not args.dry_run:
                conn.commit()
            stats["processed"] += 1
            stats["month_rows"] += result["month_rows"]
            stats["has_pab"] += int(bool(has_pab))
            stats["errors"].extend(result.get("errors", []))
            err_suffix = f", {len(result['errors'])} error(s)" if result.get("errors") else ""
            print(f"[{i + 1}/{len(pairs)}] {part_no}/{color_id}: processed "
                  f"({result['month_rows']} month-rows{err_suffix})", flush=True)
        if i < len(pairs) - 1:
            time.sleep(INTER_CALL_DELAY)

    cur.execute(COUNT_SQL)
    remaining_after = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\nDone. Processed {stats['processed']}, skipped (transient) {stats['skipped_transient']}.")
    if stats["processed"]:
        print(f"  Month-rows written   : {stats['month_rows']}")
    if stats["errors"]:
        print(f"  Errors (skipped)     : {len(stats['errors'])}")
    print(f"  Remaining            : {remaining_after:,}")

    if not args.dry_run:
        duration_s = time.monotonic() - start_time
        send_report(stats, remaining_after, duration_s)


if __name__ == "__main__":
    main()
