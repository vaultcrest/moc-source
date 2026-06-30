#!/usr/bin/env python3
"""
PAB multi-region scraper — writes directly to PostgreSQL.

Loops over all confirmed LEGO PAB locales, upserts into lego_element_prices.
Also updates lego_elements price/channel from en-us to keep the existing API current.

Usage:
    DATABASE_URL=postgresql://... python scripts/scrape_pab.py [--locale en-us] [--dry-run]
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
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────────────────

LOCALES = [
    "en-us", "en-gb", "en-au", "de-de", "fr-fr", "nl-nl",
    "en-ca", "ko-kr", "pl-pl", "sv-se", "en-nz", "cs-cz",
    "da-dk", "fi-fi", "nb-no", "es-es", "it-it", "pt-pt",
]

# OOS status is 100% shared within each group (confirmed by DB analysis —
# zero elements differ in in_stock across any pair of EU/AU/NZ/GB locales,
# and US/CA are identical to each other). Scraping one representative per
# group is sufficient to detect in-stock / out-of-stock transitions.
LOCALE_GROUPS: dict[str, list[str]] = {
    "na": ["en-us", "en-ca"],
    "eu": [
        "pl-pl", "de-de", "fr-fr", "nl-nl", "es-es", "it-it", "pt-pt",
        "cs-cz", "da-dk", "fi-fi", "nb-no", "sv-se", "en-gb", "en-au", "en-nz",
    ],
    "kr": ["ko-kr"],
}
# Representative locale per group for OOS-check runs.
# Poland chosen for EU — LEGO's primary PAB distribution warehouse is in Poland.
OOS_LOCALES = ["en-us", "pl-pl", "ko-kr"]


def get_group_siblings(locale: str) -> list[str]:
    for group in LOCALE_GROUPS.values():
        if locale in group:
            return [loc for loc in group if loc != locale]
    return []

PAB_URL = "https://www.lego.com/api/graphql/PickABrickQuery"

PAB_QUERY = """
query PickABrickQuery($input: ElementQueryInput!) {
  searchElements(input: $input) {
    results {
      ...ElementLeaf
      __typename
    }
    total
    count
    __typename
  }
}

fragment ElementLeaf on SearchResultElement {
  id
  designId
  name
  imageUrl
  maxOrderQuantity
  deliveryChannel
  colorHex

  price {
    centAmount
    formattedAmount
    currencyCode
    __typename
  }

  siblings {
    id
    availability
    price {
      centAmount
      formattedAmount
      currencyCode
      __typename
    }
    __typename
  }

  availability
  __typename
}
"""

PER_PAGE = 400
INTER_PAGE_DELAY = 1.5   # seconds between pages
INTER_LOCALE_DELAY = 5.0  # seconds between locales

# ─── LEGO fetch ──────────────────────────────────────────────────────────────

def _post_pab(body: dict, headers: dict) -> list[dict]:
    resp = curl_requests.post(PAB_URL, json=body, headers=headers, impersonate="chrome124", timeout=60)
    if resp.status_code == 429 or resp.status_code == 1015 or "rate limit" in resp.text.lower():
        raise Exception(f"RATE_LIMITED HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()["data"]["searchElements"]["results"]


def fetch_locale(locale: str, conn=None, use_sibling_cache: bool = False) -> tuple[list[dict], list[str]]:
    """
    Returns (all_results, cached_sibling_ids).
    all_results: all elements including cached siblings merged with fresh pass 1 data.
    cached_sibling_ids: sibling IDs whose channel came from DB (logged only).
    """
    headers = {
        "Origin": "https://www.lego.com",
        "Referer": f"https://www.lego.com/{locale}/pick-and-build/pick-a-brick",
        "x-locale": locale.split("-")[0].lower() + "-" + locale.split("-")[1].upper(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # ── Pass 1: paginated full scrape ──────────────────────────────────────────
    top_level: dict[str, dict] = {}   # id → item (top-level results, channel is accurate)
    sibling_ids: list[str] = []       # ids that only appeared as siblings
    sibling_raw: dict[str, dict] = {} # id → raw sibling object (has availability + price)
    page = 1

    while True:
        print(f"  [{locale}] page {page} ...", flush=True)
        results = _post_pab({
            "operationName": "PickABrickQuery",
            "variables": {"input": {
                "page": page, "perPage": PER_PAGE,
                "sort": {"key": "RELEVANCE", "direction": "DESC"},
                "query": "", "fetchSiblings": True,
                "availability": ["AVAILABLE", "OUT_OF_STOCK"],
            }},
            "query": PAB_QUERY,
        }, headers)

        if not results:
            break

        for item in results:
            top_level[item["id"]] = item
            for sib in item.get("siblings", []):
                if sib["id"] not in top_level:
                    sibling_ids.append(sib["id"])
                    sibling_raw[sib["id"]] = sib  # save availability + price for cache merge

        if len(results) < PER_PAGE:
            break
        page += 1
        time.sleep(INTER_PAGE_DELAY)

    # ── Pass 2: re-query siblings by element ID so each appears as a top-level
    # result with its own deliveryChannel (siblings in pass 1 don't expose it).
    new_sibling_ids = [sid for sid in sibling_ids if sid not in top_level]

    # Cache only delivery channel (pab/bap) from DB — never 'oos'.
    # Availability and price always come fresh from pass 1 sibling data,
    # so OOS transitions and restocks are detected on every run.
    # Parts returning from OOS are never cached (channel='oos' excluded) so
    # they get a full LEGO re-query and pick up their real delivery channel.
    cached_sibling_ids: list[str] = []
    actually_unknown = new_sibling_ids

    if conn and new_sibling_ids and (locale != "en-us" or use_sibling_cache):
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT element_id::text, channel
                    FROM lego_element_prices
                    WHERE locale = %s
                      AND element_id = ANY(%s)
                      AND channel NOT IN ('unknown', 'oos')
                      AND channel IS NOT NULL
                """, (locale, [int(sid) for sid in new_sibling_ids]))
                cached_channels = {str(row[0]): row[1] for row in cur.fetchall()}

            for sid, channel in cached_channels.items():
                if sid not in top_level:
                    sib = sibling_raw.get(sid, {})
                    top_level[sid] = {
                        "id": sid,
                        "deliveryChannel": channel,
                        "availability": sib.get("availability") or "AVAILABLE",
                        "price": sib.get("price") or {},
                    }
                    cached_sibling_ids.append(sid)

            actually_unknown = [sid for sid in new_sibling_ids if sid not in top_level]
            if cached_sibling_ids:
                print(f"  [{locale}] {len(cached_sibling_ids)} siblings: channel cached, "
                      f"avail/price fresh from pass 1; {len(actually_unknown)} need LEGO query", flush=True)
        except Exception as e:
            print(f"  [{locale}] DB cache query failed ({e}), re-querying all siblings", file=sys.stderr)
            cached_sibling_ids = []
            actually_unknown = new_sibling_ids

    BATCH = 900  # IDs per query string (LEGO accepts up to ~900)
    for b_start in range(0, len(actually_unknown), BATCH):
        batch = actually_unknown[b_start:b_start + BATCH]
        query_str = " ".join(batch)
        print(f"  [{locale}] sibling lookup {b_start+1}–{b_start+len(batch)} of {len(actually_unknown)} ...", flush=True)
        sib_page = 1
        while True:
            try:
                results = _post_pab({
                    "operationName": "PickABrickQuery",
                    "variables": {"input": {
                        "page": sib_page, "perPage": PER_PAGE,
                        "query": query_str,
                        "availability": ["AVAILABLE", "OUT_OF_STOCK"],
                        "fetchSiblings": False,
                    }},
                    "query": PAB_QUERY,
                }, headers)
            except Exception as e:
                print(f"  [{locale}] sibling batch page {sib_page} failed: {e}", file=sys.stderr)
                break
            for item in results:
                top_level[item["id"]] = item
            if len(results) < PER_PAGE:
                break
            sib_page += 1
            time.sleep(INTER_PAGE_DELAY)

    all_results = list(top_level.values())
    print(f"  [{locale}] fetched {len(all_results)} elements total "
          f"({len(cached_sibling_ids)} DB cache, {len(actually_unknown)} LEGO API)", flush=True)
    return all_results, cached_sibling_ids


# ─── Transform ───────────────────────────────────────────────────────────────

def parse_item(item: dict, locale: str) -> dict | None:
    try:
        element_id = int(item["id"])
    except (KeyError, ValueError, TypeError):
        return None

    price = item.get("price") or {}
    channel_raw = item.get("deliveryChannel")
    channel = channel_raw.lower() if channel_raw else (
        "oos" if item.get("availability") == "OUT_OF_STOCK" else "unknown"
    )

    return {
        "element_id": element_id,
        "locale": locale,
        "channel": channel,
        "price_cents": price.get("centAmount"),
        "price_formatted": price.get("formattedAmount"),
        "currency_code": price.get("currencyCode"),
        "in_stock": item.get("availability") == "AVAILABLE",
        "design_id": str(item.get("designId", "")) or None,
        "lego_name": item.get("name"),
        "updated_at": datetime.now(timezone.utc),
    }


# ─── DB writes ───────────────────────────────────────────────────────────────

UPSERT_PRICES = """
INSERT INTO lego_element_prices
    (element_id, locale, channel, price_cents, price_formatted, currency_code, in_stock, updated_at)
VALUES %s
ON CONFLICT (element_id, locale) DO UPDATE SET
    channel         = EXCLUDED.channel,
    price_cents     = EXCLUDED.price_cents,
    price_formatted = EXCLUDED.price_formatted,
    currency_code   = EXCLUDED.currency_code,
    in_stock        = EXCLUDED.in_stock,
    updated_at      = EXCLUDED.updated_at
"""

# Full upsert for en-us — updates pricing and availability
UPSERT_ELEMENTS_EN_US = """
INSERT INTO lego_elements
    (element_id, design_id, lego_name, channel, price_cents, price_formatted, last_seen, first_seen, updated_at)
VALUES %s
ON CONFLICT (element_id) DO UPDATE SET
    design_id       = EXCLUDED.design_id,
    lego_name       = EXCLUDED.lego_name,
    channel         = EXCLUDED.channel,
    price_cents     = EXCLUDED.price_cents,
    price_formatted = EXCLUDED.price_formatted,
    last_seen       = EXCLUDED.last_seen,
    updated_at      = EXCLUDED.updated_at
"""

# For non-en-us locales: create FK parent row if new, or just refresh updated_at so the
# stale-detection query doesn't falsely mark cross-locale-only elements as 'oos'.
INSERT_ELEMENTS_NEW_ONLY = """
INSERT INTO lego_elements
    (element_id, design_id, lego_name, first_seen, updated_at)
VALUES %s
ON CONFLICT (element_id) DO UPDATE SET
    updated_at = EXCLUDED.updated_at
"""

# Elements no longer returned by LEGO's API for a locale (discontinued/pulled):
# mark out of stock so the extension and API stop surfacing them.
MARK_STALE_PRICES_OOS = """
UPDATE lego_element_prices
SET    in_stock   = false,
       updated_at = %(now)s
WHERE  locale     = %(locale)s
  AND  updated_at < %(run_start)s
  AND  in_stock   = true
"""

# For en-us canonical table: channel → 'oos' for anything not seen this run.
MARK_STALE_ELEMENTS_OOS = """
UPDATE lego_elements
SET    channel    = 'oos',
       updated_at = %(now)s
WHERE  updated_at < %(run_start)s
  AND  channel   != 'oos'
"""


def ensure_elements_exist(cur, rows: list[dict], now: datetime) -> int:
    values = [
        (r["element_id"], r["design_id"], r["lego_name"], now, now)
        for r in rows
    ]
    psycopg2.extras.execute_values(cur, INSERT_ELEMENTS_NEW_ONLY, values, page_size=500)
    return cur.rowcount


def write_prices(cur, rows: list[dict]) -> int:
    values = [
        (
            r["element_id"], r["locale"], r["channel"],
            r["price_cents"], r["price_formatted"], r["currency_code"],
            r["in_stock"], r["updated_at"],
        )
        for r in rows
    ]
    psycopg2.extras.execute_values(cur, UPSERT_PRICES, values, page_size=500)
    return len(values)


def write_elements_en_us(cur, rows: list[dict], now: datetime) -> int:
    values = [
        (
            r["element_id"], r["design_id"], r["lego_name"],
            r["channel"], r["price_cents"], r["price_formatted"],
            now, now, now,
        )
        for r in rows
    ]
    psycopg2.extras.execute_values(cur, UPSERT_ELEMENTS_EN_US, values, page_size=500)
    return len(values)


# ─── Email report ────────────────────────────────────────────────────────────

def send_scraper_report(locales_done: int, total_locales: int, total_prices: int,
                        total_elements: int, errors: list[str], duration_s: float) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    status  = "OK" if not errors else f"{len(errors)} error(s)"
    subject = f"[MOC Source] PAB Scraper: {status} — {locales_done}/{total_locales} locales, {total_prices:,} rows"
    mins, secs = divmod(int(duration_s), 60)
    body = (
        f"PAB scraper run complete.\n\n"
        f"Locales scraped : {locales_done}/{total_locales}\n"
        f"Price rows      : {total_prices:,}\n"
        f"Element rows    : {total_elements:,}\n"
        f"Duration        : {mins}m {secs}s\n"
    )
    if errors:
        body += "\nErrors:\n" + "\n".join(f"  • {e}" for e in errors)

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
        print(f"Run report emailed to {report_email}", flush=True)
    except Exception as e:
        print(f"Failed to send report email: {e}", file=sys.stderr)


# ─── Main ────────────────────────────────────────────────────────────────────

def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # Strip async driver prefix so psycopg2 can use it
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    return url


def main():
    parser = argparse.ArgumentParser(description="Scrape PAB inventory to PostgreSQL")
    parser.add_argument("--locale", help="Scrape a single locale only (e.g. en-us)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write to DB")
    parser.add_argument(
        "--mode", choices=["full", "oos"], default="full",
        help="full: all 18 locales, prices + availability (daily). "
             "oos: 3 representative locales only, propagates in_stock to sibling locales (hourly).",
    )
    args = parser.parse_args()

    if args.mode == "oos":
        locales = OOS_LOCALES
    else:
        locales = [args.locale] if args.locale else LOCALES
    now = datetime.now(timezone.utc)
    run_start_time = time.monotonic()

    conn = None if args.dry_run else psycopg2.connect(get_db_url())

    total_prices = 0
    total_elements = 0
    run_start = now  # all writes in this run have updated_at >= now
    errors: list[str] = []
    locales_done = 0
    run_id: int | None = None

    if conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scraper_runs (mode, started_at) VALUES (%s, %s) RETURNING id",
                (args.mode, now),
            )
            run_id = cur.fetchone()[0]
        conn.commit()

    try:
        for i, locale in enumerate(locales):
            print(f"\n[{i+1}/{len(locales)}] Scraping {locale} ...", flush=True)

            try:
                raw, cached_ids = fetch_locale(
                    locale,
                    conn if not args.dry_run else None,
                    use_sibling_cache=(args.mode == "oos"),
                )
            except Exception as e:
                msg = f"{locale}: fetch failed — {e}"
                print(f"  ERROR: {msg}", file=sys.stderr)
                errors.append(msg)
                if i < len(locales) - 1:
                    time.sleep(INTER_LOCALE_DELAY)
                continue

            rows = [r for item in raw if (r := parse_item(item, locale)) is not None]
            print(f"  [{locale}] parsed {len(rows)} valid rows", flush=True)

            if args.dry_run:
                print(f"  [{locale}] dry-run, skipping DB write")
            else:
                locale_start = run_start
                with conn.cursor() as cur:
                    if locale == "en-us" and args.mode == "full":
                        # Full upsert: updates pricing + channel on existing rows,
                        # and creates any brand-new elements LEGO has added since last seed.
                        # Skipped in OOS mode — channel data is refreshed by the daily full run.
                        n2 = write_elements_en_us(cur, rows, now)
                        total_elements += n2
                        print(f"  [{locale}] upserted {n2} lego_elements rows", flush=True)
                    else:
                        # Refresh updated_at for known elements, insert new ones.
                        # Keeps the stale-element check accurate across all locales.
                        ensure_elements_exist(cur, rows, now)

                    n = write_prices(cur, rows)
                    total_prices += n

                    # Price rows not touched this run: element left this locale's PAB catalog.
                    cur.execute(MARK_STALE_PRICES_OOS, {"now": now, "locale": locale, "run_start": locale_start})
                    stale_p = cur.rowcount
                    if stale_p:
                        print(f"  [{locale}] {stale_p} price rows marked out-of-stock (left catalog)", flush=True)

                conn.commit()
                print(f"  [{locale}] committed {n} price rows", flush=True)

                # OOS mode: propagate in_stock from this representative locale
                # to all sibling locales in the same group. Prices stay from
                # the last full run — only stock status is synced here.
                if args.mode == "oos":
                    siblings = get_group_siblings(locale)
                    if siblings:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE lego_element_prices target
                                SET in_stock = source.in_stock,
                                    updated_at = %(now)s
                                FROM lego_element_prices source
                                WHERE source.locale = %(rep)s
                                  AND target.element_id = source.element_id
                                  AND target.locale = ANY(%(siblings)s)
                            """, {"now": now, "rep": locale, "siblings": siblings})
                            propagated = cur.rowcount
                        conn.commit()
                        print(f"  [{locale}] propagated in_stock → {propagated} rows "
                              f"across {len(siblings)} sibling locales", flush=True)

            locales_done += 1
            if i < len(locales) - 1:
                time.sleep(INTER_LOCALE_DELAY)

        if not args.dry_run and conn and len(locales) > 1 and args.mode == "full":
            # After ALL locales: elements not seen anywhere this run have left the PAB
            # catalog entirely — mark their canonical channel as 'oos'.
            # (Must run after all locales so cross-locale-only elements aren't falsely marked.)
            with conn.cursor() as cur:
                cur.execute(MARK_STALE_ELEMENTS_OOS, {"now": now, "run_start": run_start})
                stale_el = cur.rowcount
                if stale_el:
                    print(f"\n  {stale_el} lego_elements marked oos (no longer in any locale)", flush=True)
            conn.commit()

    finally:
        if conn and run_id:
            finished = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE scraper_runs
                    SET finished_at = %s, locales_done = %s,
                        prices_upserted = %s, errors_count = %s, success = %s
                    WHERE id = %s
                """, (finished, locales_done, total_prices, len(errors), len(errors) == 0, run_id))
            conn.commit()
        if conn:
            conn.close()

    duration_s = time.monotonic() - run_start_time
    print(f"\nDone. {total_prices:,} price rows upserted, {total_elements:,} element rows updated. "
          f"({int(duration_s//60)}m {int(duration_s%60)}s)")

    if not args.dry_run:
        send_scraper_report(locales_done, len(locales), total_prices, total_elements,
                            errors, duration_s)


if __name__ == "__main__":
    main()
