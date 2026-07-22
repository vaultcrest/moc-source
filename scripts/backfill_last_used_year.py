#!/usr/bin/env python3
"""Backfill last_used_year and year_released on bl_part_catalog via
Rebrickable's bulk parts API instead of per-part BrickLink calls.

Rebrickable's /lego/parts/?part_nums=...&inc_part_details=1&page_size=1000
(1,000 part_nums per call -- page_size must be passed explicitly, the
endpoint's own default page_size is 100 and silently truncates beyond that
with no error) already returns year_from/year_to per part -- confirmed live
2026-07-14 (part 3001 -> year_from=1979, year_to=2026). That's the exact
first-year/last-year pair scrape_bl_mold_data.py used to compute via a
paced BrickLink /supersets call per part_no, cross-referenced against the
local lego_sets table -- ~11.5 hours of BrickLink traffic for 41,473 distinct
part_nos, and incomplete for series lego_sets doesn't cover (e.g. Collectible
Minifigures, BrickLink's "col##-#" numbering). This script replaces that
entirely: no BrickLink calls, no lego_sets dependency, ~42 bulk Rebrickable
calls (~10 minutes) for the same coverage, and fixes the CMF-style gap at the
root since it doesn't depend on lego_sets at all.

Turning a BrickLink part_no into the Rebrickable part_num(s) needed for the
bulk call takes no network call: bricklink_mappings.element_id joins
directly against a local elements.csv copy (element_id -> part_num), which
covers 105,646/105,654 (99.99%) of live element_ids. The handful missing
from the local CSV fall back to a per-element live lookup via
resolve_element_via_rebrickable() (negligible volume).

One BrickLink part_no can cover several Rebrickable print-variant part_nums
(different element_ids/colors sharing one physical BL part). For each
bl_part_no: year_released = MIN(year_from) and last_used_year = MAX(year_to)
across all its rb_part_nums -- the physical part's true first/last year is
the outer bound across every variant.

last_used_year also floors at the current year for any part_no with an
element currently in-stock somewhere on PAB (2026-07-21) -- Rebrickable's
year_to only advances once it has catalogued a set released this year that
contains the part, which lags real-world PAB availability by months for an
in-progress year, and never even gets Rebrickable data at all for
still-in-production molds too new to appear in any catalogued set yet. This
never lowers a value Rebrickable already reported, only raises unresolved
or stale-current-year ones.

Full pass every run (no batching/resumability marker) -- a complete run here
is ~10 minutes, so nightly just re-syncs everything fresh. Writes only
bl_part_catalog(part_no, year_released, last_used_year, looked_up_at) --
name/item_type/category_id are now bulk-populated by
scripts/ingest_brickstore_catalog.py (2026-07-16, replaced the old
BrickLink-paced scrape_bl_mold_data.py entirely), so the two jobs own
disjoint columns and can run independently.

Usage:
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/backfill_last_used_year.py [--dry-run]
    DATABASE_URL=... REBRICKABLE_API_KEY=... python scripts/backfill_last_used_year.py --part-no 3001 27409 [--dry-run]
"""
import argparse
import csv
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import psycopg2
from _rebrickable_lookup import resolve_element_via_rebrickable, resolve_part_years_bulk
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
INTER_CALL_DELAY = 1.2  # matches the pacing already established in _rebrickable_lookup.py callers

_SERVER_DEFAULT = Path("/opt/mocsource/data/elements.csv")
try:
    _DEV_DEFAULT = Path(__file__).resolve().parents[2] / "brick_palettes_generator/data/rebrickable/elements.csv"
except IndexError:
    _DEV_DEFAULT = Path("elements.csv")
DEFAULT_ELEMENTS_CSV = _SERVER_DEFAULT if _SERVER_DEFAULT.exists() else _DEV_DEFAULT

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def load_element_to_rb_part(csv_path: Path) -> dict[int, str]:
    """Return {element_id: rb_part_num} from a local elements.csv copy."""
    mapping: dict[int, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                mapping[int(row["element_id"])] = row["part_num"]
            except (ValueError, KeyError):
                pass
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part-no", nargs="+", default=None,
                         help="process exactly these BL part_nos, bypassing the full-table query")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be written without touching the database")
    parser.add_argument("--elements-csv", type=Path, default=DEFAULT_ELEMENTS_CSV,
                         help=f"path to elements.csv (default {DEFAULT_ELEMENTS_CSV})")
    args = parser.parse_args()

    if not REBRICKABLE_API_KEY:
        print("ERROR: REBRICKABLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    if not args.elements_csv.exists():
        print(f"ERROR: {args.elements_csv} not found", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()

    print(f"Loading {args.elements_csv}…")
    eid_to_rbpart = load_element_to_rb_part(args.elements_csv)
    print(f"  {len(eid_to_rbpart)} element_id -> rb part_num entries")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    if args.part_no:
        cur.execute(
            "SELECT element_id, part_no FROM bricklink_mappings WHERE part_no = ANY(%s)",
            (args.part_no,),
        )
    else:
        cur.execute("SELECT element_id, part_no FROM bricklink_mappings WHERE part_no IS NOT NULL")
    rows = cur.fetchall()
    print(f"{len(rows)} bricklink_mappings row(s) to resolve")

    bl_to_rbparts: dict[str, set[str]] = {}
    bl_to_element_ids: dict[str, list[int]] = {}
    missing_element_ids: list[tuple[int, str]] = []
    for element_id, bl_part_no in rows:
        bl_to_element_ids.setdefault(bl_part_no, []).append(element_id)
        rb_part = eid_to_rbpart.get(element_id)
        if rb_part:
            bl_to_rbparts.setdefault(bl_part_no, set()).add(rb_part)
        else:
            missing_element_ids.append((element_id, bl_part_no))

    if missing_element_ids:
        print(f"{len(missing_element_ids)} element_id(s) not in local elements.csv — falling back to live lookup")
        for element_id, bl_part_no in missing_element_ids:
            info = resolve_element_via_rebrickable(element_id, REBRICKABLE_API_KEY)
            if info and info.get("part_num"):
                bl_to_rbparts.setdefault(bl_part_no, set()).add(info["part_num"])
            else:
                print(f"  element_id {element_id} ({bl_part_no}): no Rebrickable record found", flush=True)
            time.sleep(INTER_CALL_DELAY)

    rb_part_nums = sorted({rb for rbparts in bl_to_rbparts.values() for rb in rbparts})
    print(f"{len(rb_part_nums)} distinct Rebrickable part_num(s) to bulk-fetch "
          f"({-(-len(rb_part_nums) // 100)} call(s))")

    years = resolve_part_years_bulk(rb_part_nums, REBRICKABLE_API_KEY, inter_call_delay=INTER_CALL_DELAY)

    # A stored rb part_num can 404 against the bulk endpoint even though the
    # element_id is correct -- Rebrickable renumbers/consolidates print
    # variants over time (confirmed live 2026-07-21 via Rebrickable's own
    # part changelog: 92456c10pr0241 -> 92456c25pr0001, renamed 2026-07-10,
    # well after our local elements.csv snapshot). The element_id stays
    # stable across renumbering, so retry via the per-element endpoint for
    # anything the bulk call found zero record of at all -- cheap, since
    # this only ever runs for the handful still unresolved after the bulk
    # pass (58 as of 2026-07-21), not the whole dataset.
    stale_part_nos = [
        bl_part_no for bl_part_no, rbparts in bl_to_rbparts.items()
        if not any(rb in years for rb in rbparts)
    ]
    if stale_part_nos:
        print(f"{len(stale_part_nos)} part_no(s) had no bulk match at all -- retrying via per-element lookup", flush=True)
        for bl_part_no in stale_part_nos:
            found_any = False
            for element_id in bl_to_element_ids.get(bl_part_no, []):
                info = resolve_element_via_rebrickable(element_id, REBRICKABLE_API_KEY)
                time.sleep(INTER_CALL_DELAY)
                if info and info.get("part_num") and (info.get("year_from") is not None or info.get("year_to") is not None):
                    new_rb_part = info["part_num"]
                    bl_to_rbparts[bl_part_no].add(new_rb_part)
                    years[new_rb_part] = (info.get("year_from"), info.get("year_to"))
                    found_any = True
            if not found_any:
                print(f"  {bl_part_no}: no year data via element fallback either", flush=True)

    # Rebrickable's year_to only advances once it has catalogued a set released
    # this year that contains the part -- for the current, still-in-progress
    # year that lags well behind real-world PAB availability (confirmed
    # 2026-07-21: ~1,100 parts currently in-stock on PAB still showed a stale
    # year_to). A part in stock on PAB right now is directly proof it's in use
    # this year, so that floors last_used_year at the current year -- it never
    # lowers a value Rebrickable already reported, and it resolves parts
    # Rebrickable has no record for at all (still-in-production molds too new
    # to have a catalogued set yet).
    cur.execute("""
        SELECT DISTINCT bm.part_no
        FROM bricklink_mappings bm
        JOIN lego_element_prices lep ON lep.element_id = bm.element_id
        WHERE lep.in_stock = true AND bm.part_no IS NOT NULL
    """)
    pab_active_part_nos = {r[0] for r in cur.fetchall()}
    print(f"{len(pab_active_part_nos)} part_no(s) currently in-stock somewhere on PAB")

    now = datetime.now(timezone.utc)
    current_year = now.year
    resolved = unresolved = pab_corroborated = 0
    for i, (bl_part_no, rbparts) in enumerate(sorted(bl_to_rbparts.items())):
        froms = [years[rb][0] for rb in rbparts if rb in years and years[rb][0] is not None]
        tos = [years[rb][1] for rb in rbparts if rb in years and years[rb][1] is not None]
        year_released = min(froms) if froms else None
        last_used_year = max(tos) if tos else None

        if bl_part_no in pab_active_part_nos and (last_used_year is None or last_used_year < current_year):
            last_used_year = current_year
            pab_corroborated += 1

        if year_released is None and last_used_year is None:
            unresolved += 1
            print(f"[{i + 1}/{len(bl_to_rbparts)}] {bl_part_no}: no year data from Rebrickable", flush=True)
            continue

        resolved += 1
        if args.dry_run:
            print(f"    [dry-run] {bl_part_no}: year_released={year_released} last_used_year={last_used_year}")
        else:
            cur.execute(
                """
                INSERT INTO bl_part_catalog (part_no, year_released, last_used_year, looked_up_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (part_no) DO UPDATE SET
                    year_released = EXCLUDED.year_released,
                    last_used_year = EXCLUDED.last_used_year,
                    looked_up_at = EXCLUDED.looked_up_at
                """,
                (bl_part_no, year_released, last_used_year, now),
            )
            if (i + 1) % 500 == 0:
                conn.commit()
                print(f"[{i + 1}/{len(bl_to_rbparts)}] committed", flush=True)

    if not args.dry_run:
        conn.commit()

    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone. Resolved: {resolved} ({pab_corroborated} via PAB in-stock), "
          f"unresolved: {unresolved}. Duration: {mins}m {secs}s")

    if not args.dry_run:
        send_report(resolved, unresolved, duration_s)


def send_report(resolved: int, unresolved: int, duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    mins, secs = divmod(int(duration_s), 60)
    subject = f"[MOC Source] last_used_year backfill: {resolved} resolved, {unresolved} unresolved"
    body = (
        "Nightly last_used_year/year_released backfill run complete (sourced from "
        "Rebrickable's bulk parts API, no BrickLink calls).\n\n"
        f"Resolved   : {resolved}\n"
        f"Unresolved : {unresolved}\n"
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


if __name__ == "__main__":
    main()
