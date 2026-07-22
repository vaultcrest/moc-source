#!/usr/bin/env python3
"""Retry BrickLink/Rebrickable mapping resolution for lego_elements rows that
still have no bricklink_mappings row at all.

enrich_new_elements() in scrape_pab.py only ever runs once, at the moment an
element first lands in lego_elements -- if that one attempt fails (rate
limit, timing, neither source having the data yet), nothing retries it
again. Found 2026-07-21: 17 currently-in-stock PAB elements stuck this way,
all of which resolved cleanly via BrickLink's own item_mapping endpoint on a
fresh attempt. This script is the recurring retry so that class of gap
doesn't need a manual fix again -- typical week should be 0-a handful of
elements.

Usage:
    DATABASE_URL=postgresql://... python scripts/retry_unmapped_elements.py [--dry-run]
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg2
from dotenv import load_dotenv
from scrape_pab import enrich_new_elements, get_db_url

load_dotenv()

FIND_UNMAPPED_SQL = """
    SELECT le.element_id
    FROM lego_elements le
    LEFT JOIN bricklink_mappings bm ON bm.element_id = le.element_id
    WHERE bm.element_id IS NULL
    ORDER BY le.element_id
"""


def send_report(resolved: list[tuple[int, str, int, str]], unresolved: list[int]) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "")
    report_email = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return
    if not resolved and not unresolved:
        return  # nothing to report -- the common case, stay quiet

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")

    bl_count = sum(1 for *_, source in resolved if source == "bricklink")
    rb_count = len(resolved) - bl_count
    subject = f"[MOC Source] Element mapping retry: {len(resolved)} resolved, {len(unresolved)} still unresolved"
    lines = [
        f"Elements with no bricklink_mappings row, retried this run: {len(resolved) + len(unresolved)}",
        f"Resolved via BrickLink   : {bl_count}",
        f"Resolved via Rebrickable : {rb_count}",
        f"Still unresolved         : {len(unresolved)}",
        "",
    ]
    if resolved:
        lines.append("Resolved:")
        lines += [f"  • {eid} -> BL part {part_no} / color {color_id} [{source}]" for eid, part_no, color_id, source in resolved]
        lines.append("")
    if unresolved:
        lines.append("Still unresolved -- neither source has this element yet:")
        lines += [f"  • {eid}" for eid in unresolved]

    msg = MIMEText("\n".join(lines))
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = report_email
    try:
        import smtplib

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
    parser.add_argument("--dry-run", action="store_true", help="resolve and print, but don't write to bricklink_mappings")
    args = parser.parse_args()

    conn = psycopg2.connect(get_db_url())
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(FIND_UNMAPPED_SQL)
    element_ids = [r[0] for r in cur.fetchall()]
    print(f"{len(element_ids)} element(s) with no bricklink_mappings row", flush=True)

    if not element_ids:
        cur.close()
        conn.close()
        return

    start = time.monotonic()
    now = datetime.now(timezone.utc)
    resolved, unresolved = enrich_new_elements(cur, element_ids, now, dry_run=args.dry_run)
    if args.dry_run:
        conn.rollback()
    else:
        conn.commit()

    for eid, part_no, color_id, source in resolved:
        print(f"  {eid} -> {part_no} / color {color_id} [{source}]", flush=True)
    print(f"Resolved: {len(resolved)}, unresolved: {len(unresolved)}, {time.monotonic() - start:.0f}s", flush=True)

    send_report(resolved, unresolved)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
