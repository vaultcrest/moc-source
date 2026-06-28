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
import sys
import time
from datetime import datetime, timezone

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
INTER_PAGE_DELAY = 0.5   # seconds between pages
INTER_LOCALE_DELAY = 2.0  # seconds between locales

# ─── LEGO fetch ──────────────────────────────────────────────────────────────

def _post_pab(body: dict, headers: dict) -> list[dict]:
    resp = curl_requests.post(PAB_URL, json=body, headers=headers, impersonate="chrome124", timeout=60)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()["data"]["searchElements"]["results"]


def fetch_locale(locale: str) -> list[dict]:
    headers = {
        "Origin": "https://www.lego.com",
        "Referer": f"https://www.lego.com/{locale}/pick-and-build/pick-a-brick",
        "x-locale": locale.split("-")[0].lower() + "-" + locale.split("-")[1].upper(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # ── Pass 1: paginated full scrape ──────────────────────────────────────────
    top_level: dict[str, dict] = {}   # id → item (top-level results, channel is accurate)
    sibling_ids: list[str] = []       # ids that only appeared as siblings
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

        if len(results) < PER_PAGE:
            break
        page += 1
        time.sleep(INTER_PAGE_DELAY)

    # ── Pass 2: re-query siblings by element ID so each appears as a top-level
    # result with its own deliveryChannel (siblings in pass 1 don't expose it).
    new_sibling_ids = [sid for sid in sibling_ids if sid not in top_level]
    BATCH = 900  # IDs per query string (LEGO accepts up to ~900)
    for b_start in range(0, len(new_sibling_ids), BATCH):
        batch = new_sibling_ids[b_start:b_start + BATCH]
        query_str = " ".join(batch)
        print(f"  [{locale}] sibling lookup {b_start+1}–{b_start+len(batch)} of {len(new_sibling_ids)} ...", flush=True)
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
    print(f"  [{locale}] fetched {len(all_results)} elements total ({len(new_sibling_ids)} siblings re-queried)", flush=True)
    return all_results


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
    args = parser.parse_args()

    locales = [args.locale] if args.locale else LOCALES
    now = datetime.now(timezone.utc)

    conn = None if args.dry_run else psycopg2.connect(get_db_url())

    total_prices = 0
    total_elements = 0
    run_start = now  # all writes in this run have updated_at >= now

    try:
        for i, locale in enumerate(locales):
            print(f"\n[{i+1}/{len(locales)}] Scraping {locale} ...", flush=True)

            raw = fetch_locale(locale)
            rows = [r for item in raw if (r := parse_item(item, locale)) is not None]
            print(f"  [{locale}] parsed {len(rows)} valid rows", flush=True)

            if args.dry_run:
                print(f"  [{locale}] dry-run, skipping DB write")
            else:
                locale_start = run_start
                with conn.cursor() as cur:
                    if locale == "en-us":
                        # Full upsert: updates pricing + channel on existing rows,
                        # and creates any brand-new elements LEGO has added since last seed
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

            if i < len(locales) - 1:
                time.sleep(INTER_LOCALE_DELAY)

        if not args.dry_run and conn and len(locales) > 1:
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
        if conn:
            conn.close()

    print(f"\nDone. {total_prices} price rows upserted, {total_elements} element rows updated.")


if __name__ == "__main__":
    main()
