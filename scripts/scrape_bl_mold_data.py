#!/usr/bin/env python3
"""Backfill BrickLink mold-family (alternate_no) and last-used-year data.

For every part_no in bricklink_mappings, fetches BrickLink's catalog entry
(for alternate_no — sibling mold numbers) and its supersets (every set
containing the part, used to compute last_used_year via the local lego_sets
table — no extra BL call per set needed).

Foundation for discontinued-part / newer-mold detection: a part whose
last_used_year is old is a candidate to suggest a newer sibling mold from
its alternate_no family instead.

Resumable: re-running only processes part_nos whose bl_part_catalog row
still has mold_backfilled_at IS NULL — a dedicated marker, separate from
looked_up_at (which is also set by the unrelated live-request cache path in
routers/parts.py; using that as the gate previously caused parts already
cached by that older path to be silently skipped forever). A part genuinely
never used in any set (or not found in BL's catalog at all) still gets
mold_backfilled_at set, so it's not retried forever — only real
network/rate-limit failures are left for retry.

Emails a per-run summary (or, once the backfill has nothing left, a distinct
completion notice) via SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/
REPORT_EMAIL, same convention as scrape_pab.py. No-ops if SMTP_HOST or
REPORT_EMAIL aren't set. Skipped entirely in --dry-run.

Usage:
    DATABASE_URL=... python scripts/scrape_bl_mold_data.py [--batch-size 100]
    DATABASE_URL=... python scripts/scrape_bl_mold_data.py --part-no 3684a 3684c [--dry-run]
"""
import argparse
import base64
import hashlib
import hmac
import os
import smtplib
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv()

BRICKLINK_CONSUMER_KEY = os.environ.get("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.environ.get("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.environ.get("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.environ.get("BRICKLINK_TOKEN_SECRET", "")

BL_API_BASE = "https://api.bricklink.com/api/store/v1"
INTER_CALL_DELAY = 1.0  # polite pacing, matches scrape_pab.py's enrichment convention
DEFAULT_BATCH_SIZE = 100
MAX_CONSECUTIVE_FAILURES = 5

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BATCH_SQL = """
    SELECT DISTINCT bm.part_no
    FROM bricklink_mappings bm
    LEFT JOIN bl_part_catalog bpc ON bpc.part_no = bm.part_no
    WHERE bpc.mold_backfilled_at IS NULL
      AND bm.part_no IS NOT NULL
    ORDER BY bm.part_no
    LIMIT %s
"""

COUNT_SQL = """
    SELECT count(DISTINCT bm.part_no)
    FROM bricklink_mappings bm
    LEFT JOIN bl_part_catalog bpc ON bpc.part_no = bm.part_no
    WHERE bpc.mold_backfilled_at IS NULL
      AND bm.part_no IS NOT NULL
"""


def _bl_oauth1_header(method: str, url: str) -> str:
    params = {
        "oauth_consumer_key":     BRICKLINK_CONSUMER_KEY,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            BRICKLINK_TOKEN,
        "oauth_version":          "1.0",
    }
    enc = urllib.parse.quote
    param_string = "&".join(f"{enc(k, safe='')}={enc(v, safe='')}" for k, v in sorted(params.items()))
    base_string = "&".join([method.upper(), enc(url, safe=""), enc(param_string, safe="")])
    signing_key = enc(BRICKLINK_CONSUMER_SECRET, safe="") + "&" + enc(BRICKLINK_TOKEN_SECRET, safe="")
    sig = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    params["oauth_signature"] = base64.b64encode(sig).decode()
    return "OAuth " + ", ".join(f'{enc(k, safe="")}="{enc(v, safe="")}"' for k, v in sorted(params.items()))


def _bl_get(url: str, label: str, part_no: str):
    """Shared retry loop. Returns (attempted, resp_or_none).

    attempted=True means BL gave an authoritative answer (200, or a 4xx that
    isn't 429) — the caller should persist looked_up_at regardless of
    whether any data came back. attempted=False means a transient failure
    (network error, 429, 5xx) exhausted its retries — the caller must not
    write anything, so the next run retries this part_no.
    """
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"Authorization": _bl_oauth1_header("GET", url)}, timeout=8)
        except requests.exceptions.RequestException as e:
            if attempt == 2:
                print(f"  BL {label} network failure for {part_no}: {e}", file=sys.stderr)
                return False, None
            time.sleep(2 * (attempt + 1))
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == 2:
                print(f"  BL {label} rate-limited/server error for {part_no}: HTTP {resp.status_code}", file=sys.stderr)
                return False, None
            time.sleep(2 * (attempt + 1))
            continue

        return True, resp
    return False, None


def fetch_bl_catalog_item(part_no: str) -> tuple[bool, dict | None]:
    """Fetch (name, item_type, alternate_no) for a part_no. Mirrors the parsing
    in mocsource/bl_client.py's _fetch_part_sync."""
    url = f"{BL_API_BASE}/items/PART/{urllib.parse.quote(part_no, safe='')}"
    attempted, resp = _bl_get(url, "catalog", part_no)
    if not attempted:
        return False, None
    if resp.status_code == 404:
        return True, None
    if resp.status_code != 200:
        print(f"  BL catalog unexpected status for {part_no}: HTTP {resp.status_code}", file=sys.stderr)
        return True, None

    data = resp.json().get("data")
    if not data:
        return True, None
    raw_alt = data.get("alternate_no") or ""
    if isinstance(raw_alt, str):
        alternates = [p.strip() for p in raw_alt.split(",") if p.strip()]
    else:
        alternates = [str(p).strip() for p in raw_alt if str(p).strip()]
    return True, {
        "name": data.get("name"),
        "item_type": data.get("type"),
        "alternate_no": alternates,
        "year_released": data.get("year_released"),
    }


def fetch_bl_supersets(part_no: str) -> tuple[bool, list[str] | None]:
    """Fetch every distinct SET number containing part_no, across all colors."""
    url = f"{BL_API_BASE}/items/PART/{urllib.parse.quote(part_no, safe='')}/supersets"
    attempted, resp = _bl_get(url, "supersets", part_no)
    if not attempted:
        return False, None
    if resp.status_code == 404:
        return True, []
    if resp.status_code != 200:
        print(f"  BL supersets unexpected status for {part_no}: HTTP {resp.status_code}", file=sys.stderr)
        return True, []

    data = resp.json().get("data") or []
    set_nos: set[str] = set()
    for group in data:
        for entry in group.get("entries", []):
            item = entry.get("item", {})
            if item.get("type") == "SET" and item.get("no"):
                set_nos.add(item["no"])
    return True, sorted(set_nos)


def compute_last_used_year(cur, set_nos: list[str]) -> int | None:
    if not set_nos:
        return None
    cur.execute("SELECT MAX(year) FROM lego_sets WHERE set_num = ANY(%s)", (set_nos,))
    return cur.fetchone()[0]


def process_part(cur, part_no: str, now: datetime, dry_run: bool) -> dict:
    catalog_attempted, catalog_data = fetch_bl_catalog_item(part_no)
    time.sleep(INTER_CALL_DELAY)
    supersets_attempted, set_nos = fetch_bl_supersets(part_no)

    if not catalog_attempted or not supersets_attempted:
        return {"status": "skipped_transient"}

    name = catalog_data.get("name") if catalog_data else None
    item_type = catalog_data.get("item_type") if catalog_data else None
    raw_alts = catalog_data.get("alternate_no", []) if catalog_data else []
    year_released = catalog_data.get("year_released") if catalog_data else None
    last_used_year = compute_last_used_year(cur, set_nos or [])
    filtered_alts = sorted({a for a in raw_alts if a and a != part_no})

    if dry_run:
        print(f"    [dry-run] {part_no}: name={name!r} item_type={item_type!r} "
              f"year_released={year_released} last_used_year={last_used_year} alternates={filtered_alts}")
    else:
        cur.execute(
            """
            INSERT INTO bl_part_catalog
                (part_no, name, item_type, last_used_year, year_released, looked_up_at, mold_backfilled_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (part_no) DO UPDATE SET
                name = EXCLUDED.name,
                item_type = EXCLUDED.item_type,
                last_used_year = EXCLUDED.last_used_year,
                year_released = EXCLUDED.year_released,
                looked_up_at = EXCLUDED.looked_up_at,
                mold_backfilled_at = EXCLUDED.mold_backfilled_at
            """,
            (part_no, name, item_type, last_used_year, year_released, now, now),
        )
        cur.execute("DELETE FROM bricklink_alternates WHERE part_no = %s", (part_no,))
        if filtered_alts:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO bricklink_alternates (part_no, alternate_no) VALUES %s ON CONFLICT DO NOTHING",
                [(part_no, a) for a in filtered_alts],
                page_size=100,
            )

    return {
        "status": "processed",
        "has_alternates": bool(filtered_alts),
        "has_last_used_year": last_used_year is not None,
        "has_year_released": year_released is not None,
    }


def send_backfill_report(stats: dict, remaining_after: int, duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    processed = stats["processed"]
    mins, secs = divmod(int(duration_s), 60)
    alt_line = f"  Alternates found     : {stats['has_alternates']}/{processed}\n" if processed else ""
    year_line = f"  Last-used-year found : {stats['has_last_used_year']}/{processed}\n" if processed else ""
    released_line = f"  Year-released found  : {stats['has_year_released']}/{processed}\n" if processed else ""

    if remaining_after == 0:
        subject = "[MOC Source] BL mold-data backfill COMPLETE"
        body = (
            "The BL mold-data backfill has finished — every known part_no now has "
            "last_used_year / alternate_no data (or a confirmed no-data result).\n\n"
            f"This run   : processed {processed}, skipped (transient) {stats['skipped_transient']}\n"
            f"{alt_line}{year_line}{released_line}"
            f"Duration   : {mins}m {secs}s\n\n"
            "Nightly runs will keep firing but will find nothing left to do until new "
            "parts are added to bricklink_mappings.\n"
        )
    else:
        subject = f"[MOC Source] BL mold-data backfill: {processed} processed, {remaining_after:,} remaining"
        body = (
            "Nightly BL mold-data backfill run complete.\n\n"
            f"Processed            : {processed}\n"
            f"Skipped (transient)  : {stats['skipped_transient']}\n"
            f"{alt_line}{year_line}{released_line}"
            f"Remaining after this run: {remaining_after:,}\n"
            f"Duration   : {mins}m {secs}s\n"
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
                         help=f"how many part_nos to process this run (default {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--part-no", nargs="+", default=None,
                         help="process exactly these part_nos, bypassing the resumable batch query")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    args = parser.parse_args()

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.part_no:
        part_nos = args.part_no
        print(f"Processing {len(part_nos)} explicitly-specified part_no(s)")
    else:
        cur.execute(COUNT_SQL)
        remaining = cur.fetchone()[0]
        cur.execute(BATCH_SQL, (args.batch_size,))
        part_nos = [r[0] for r in cur.fetchall()]
        print(f"{remaining} unprocessed part_no(s) total; selected {len(part_nos)} for this run")

    if not part_nos:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    stats = {"processed": 0, "skipped_transient": 0, "has_alternates": 0, "has_last_used_year": 0, "has_year_released": 0}
    consecutive_failures = 0
    now = datetime.now(timezone.utc)

    for i, part_no in enumerate(part_nos):
        result = process_part(cur, part_no, now, args.dry_run)
        if result["status"] == "skipped_transient":
            stats["skipped_transient"] += 1
            consecutive_failures += 1
            print(f"[{i + 1}/{len(part_nos)}] {part_no}: skipped (transient failure)", flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"{MAX_CONSECUTIVE_FAILURES} consecutive transient failures — aborting batch early",
                      file=sys.stderr)
                break
        else:
            consecutive_failures = 0
            if not args.dry_run:
                conn.commit()
            stats["processed"] += 1
            stats["has_alternates"] += int(result["has_alternates"])
            stats["has_last_used_year"] += int(result["has_last_used_year"])
            stats["has_year_released"] += int(result["has_year_released"])
            print(f"[{i + 1}/{len(part_nos)}] {part_no}: processed "
                  f"(alternates={'yes' if result['has_alternates'] else 'no'}, "
                  f"last_used_year={'yes' if result['has_last_used_year'] else 'no'}, "
                  f"year_released={'yes' if result['has_year_released'] else 'no'})", flush=True)
        if i < len(part_nos) - 1:
            time.sleep(INTER_CALL_DELAY)

    cur.execute(COUNT_SQL)
    remaining_after = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\nDone. Processed {stats['processed']}, skipped (transient) {stats['skipped_transient']}.")
    if stats["processed"]:
        print(f"  Alternates found     : {stats['has_alternates']}/{stats['processed']}")
        print(f"  Last-used-year found : {stats['has_last_used_year']}/{stats['processed']}")
        print(f"  Year-released found  : {stats['has_year_released']}/{stats['processed']}")
    print(f"  Remaining            : {remaining_after:,}")

    if not args.dry_run:
        duration_s = time.monotonic() - start_time
        send_backfill_report(stats, remaining_after, duration_s)


if __name__ == "__main__":
    main()
