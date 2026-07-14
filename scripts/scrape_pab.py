#!/usr/bin/env python3
"""
PAB multi-region scraper — writes directly to PostgreSQL.

Loops over all confirmed LEGO PAB locales, upserts into lego_element_prices.
Also updates lego_elements price/channel from en-us to keep the existing API current.

Usage:
    DATABASE_URL=postgresql://... python scripts/scrape_pab.py [--locale en-us] [--dry-run]
"""

import argparse
import base64
import hashlib
import hmac
import json as _json
import os
import smtplib
import subprocess
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg2
import psycopg2.extras
import requests
from _rebrickable_lookup import resolve_element_via_rebrickable
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
BRICKLINK_CONSUMER_KEY = os.environ.get("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.environ.get("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.environ.get("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.environ.get("BRICKLINK_TOKEN_SECRET", "")

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
OOS_LOCALES = ["en-us", "de-de", "ko-kr"]


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

PER_PAGE = 150  # fetchSiblings=True is expensive; 150 keeps per-page cost below LEGO's timeout
INTER_PAGE_DELAY = 2.0   # seconds between pages
INTER_LOCALE_DELAY = 30.0  # seconds between locales (rate-limit recovery)

# ─── LEGO fetch ──────────────────────────────────────────────────────────────

def _post_pab(body: dict, headers: dict) -> list[dict]:
    # Use the system curl binary (OpenSSL TLS fingerprint) — Python HTTP libraries
    # use a different fingerprint that Cloudflare Bot Management flags.
    cmd = [
        "curl", "-s", "-X", "POST", PAB_URL,
        "-H", "Content-Type: application/json",
        "-H", f"Origin: {headers.get('Origin', 'https://www.lego.com')}",
        "-H", f"Referer: {headers.get('Referer', '')}",
        "-H", f"x-locale: {headers.get('x-locale', '')}",
        "-H", f"User-Agent: {headers.get('User-Agent', '')}",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Accept: application/json, text/plain, */*",
        "--data", _json.dumps(body),
        "--max-time", "60",
        "-w", "\n%{http_code}",
    ]
    for attempt in range(3):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
        except subprocess.TimeoutExpired:
            raise Exception("curl subprocess timed out after 65s")
        parts = result.stdout.rsplit("\n", 1)
        try:
            status = int(parts[-1].strip())
            text = parts[0] if len(parts) > 1 else ""
        except ValueError:
            raise Exception(f"curl gave unexpected output: {result.stdout[:200]}")
        if status == 429 or status == 1015 or "rate limit" in text.lower():
            raise Exception(f"RATE_LIMITED HTTP {status}: {text[:200]}")
        if status == 504:
            wait = 30 * (attempt + 1)   # 30s, 60s, 90s
            print(f"  504 on attempt {attempt + 1}, retrying in {wait}s …", flush=True)
            time.sleep(wait)
            continue
        if status != 200:
            raise Exception(f"HTTP {status}: {text[:200]}")
        payload = _json.loads(text)
        if payload.get("errors"):
            raise Exception(f"GraphQL error: {payload['errors'][:2]}")
        search = (payload.get("data") or {}).get("searchElements") or {}
        return search.get("results") or []
    raise Exception("HTTP 504: upstream request timeout (3 attempts exhausted)")


def fetch_locale(locale: str, conn=None, use_sibling_cache: bool = False,
                 fetch_siblings: bool = True) -> tuple[list[dict], list[str], bool]:
    """
    Returns (all_results, cached_sibling_ids, scan_complete).

    scan_complete is True only when all pages and sibling batches succeeded
    with no errors. Callers should skip stale-detection when it is False to
    avoid incorrectly marking unseen elements as out-of-stock.

    fetch_siblings=True (both modes): fetchSiblings=True returns one design
    group per page with all color-variant siblings embedded. A second pass
    re-queries siblings by element ID to get their deliveryChannel.
    The OOS path additionally uses a DB channel cache to minimise LEGO API
    calls; the full path always re-queries so channel data is authoritative.
    """
    headers = {
        "Origin": "https://www.lego.com",
        "Referer": f"https://www.lego.com/{locale}/pick-and-build/pick-a-brick",
        "x-locale": locale.split("-")[0].lower() + "-" + locale.split("-")[1].upper(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
    }

    scan_complete = True  # set False if any page or batch errors out

    # ── Pass 1: paginated scrape with fetchSiblings=True ──────────────────────
    top_level: dict[str, dict] = {}
    sibling_ids: list[str] = []
    sibling_raw: dict[str, dict] = {}
    page = 1

    while True:
        print(f"  [{locale}] page {page} ...", flush=True)
        try:
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
        except Exception as e:
            if page > 1 and top_level:
                print(f"  [{locale}] page {page} failed ({e}); using {len(top_level)} elements from pages 1–{page-1}", flush=True)
                scan_complete = False
                break
            raise
        if not results:
            break
        for item in results:
            top_level[item["id"]] = item
            for sib in item.get("siblings", []):
                if sib["id"] not in top_level:
                    sibling_ids.append(sib["id"])
                    sibling_raw[sib["id"]] = sib
        if len(results) < PER_PAGE:
            break
        page += 1
        time.sleep(INTER_PAGE_DELAY)

    # ── Pass 2: deliveryChannel for siblings ──────────────────────────────────
    new_sibling_ids = [sid for sid in sibling_ids if sid not in top_level]
    cached_sibling_ids: list[str] = []
    actually_unknown = new_sibling_ids

    # OOS mode uses a DB channel cache so only newly-seen siblings need a LEGO
    # re-query. Full mode skips the cache so channel data is always fresh.
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

    BATCH = 300
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
                scan_complete = False
                break
            for item in results:
                top_level[item["id"]] = item
            if len(results) < PER_PAGE:
                break
            sib_page += 1
            time.sleep(INTER_PAGE_DELAY)

    all_results = list(top_level.values())
    print(f"  [{locale}] fetched {len(all_results)} elements total "
          f"({len(cached_sibling_ids)} DB cache, {len(actually_unknown)} LEGO API)"
          + ("" if scan_complete else " [INCOMPLETE — stale detection skipped]"), flush=True)
    return all_results, cached_sibling_ids, scan_complete


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


# ─── Element enrichment (new elements only) ──────────────────────────────────
#
# Only ever called for elements that entered lego_elements for the first time
# this run — NOT for every unmapped part a user happens to browse on BrickLink.
# The old per-request enrichment (one Rebrickable call per unmapped part+color
# a user viewed) generated far too much traffic and got this server IP-banned.
# New PAB elements are rare (a handful per day at most), so resolving BL
# mapping once here, at scrape time, stays well within any API's limits.
#
# Resolution order mirrors brick_palettes_generator's resolve_mapping(): try
# BrickLink's own item_mapping endpoint first (authoritative), and only fall
# back to Rebrickable when BL has nothing for that element.

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


def fetch_bl_item_mapping(element_id: int) -> dict | None:
    """Look up (part_no, color_id, item_type) for a LEGO element_id via BrickLink's
    own item_mapping endpoint — the authoritative source, tried before Rebrickable."""
    if not BRICKLINK_CONSUMER_KEY:
        return None
    url = f"https://api.bricklink.com/api/store/v1/item_mapping/{element_id}"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"Authorization": _bl_oauth1_header("GET", url)}, timeout=8)
            if resp.status_code != 200:
                return None
            data = resp.json().get("data")
            if not data:
                return None
            mapping = data[0]
            return {
                "part_no": mapping["item"]["no"],
                "color_id": mapping["color_id"],
                "item_type": mapping["item"]["type"],
            }
        except requests.exceptions.RequestException as e:
            if attempt == 2:
                print(f"  BrickLink item_mapping network failure for element {element_id}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  BrickLink item_mapping lookup failed for element {element_id}: {e}", file=sys.stderr)
            return None
    return None


def fetch_rebrickable_mapping(element_id: int) -> tuple[str, int, str | None] | None:
    """Look up (bl_part_no, bl_color_id, part_name) for a LEGO element_id via Rebrickable.

    Fallback only — tried when fetch_bl_item_mapping() has nothing for this element.
    """
    info = resolve_element_via_rebrickable(element_id, REBRICKABLE_API_KEY)
    if not info or not info["bl_part_no"] or info["bl_color_id"] is None:
        return None
    return info["bl_part_no"], info["bl_color_id"], info["part_name"]


INSERT_BL_MAPPING_NEW_ONLY = """
INSERT INTO bricklink_mappings
    (element_id, part_no, color_id, item_type, part_name, source, updated_at)
VALUES %s
ON CONFLICT (element_id) DO NOTHING
"""


def enrich_new_elements(
    cur, new_element_ids: list[int], now: datetime
) -> tuple[list[tuple[int, str, int, str]], list[int]]:
    """Resolve BL part_no/color_id for brand-new LEGO elements.

    Tries BrickLink's own item_mapping endpoint first, falling back to
    Rebrickable only when BL has no mapping for that element.

    Returns (resolved, unresolved) — resolved is a list of
    (element_id, bl_part_no, bl_color_id, source) tuples where source is
    "bricklink" or "rebrickable"; unresolved is element_ids neither had data for.
    """
    if not BRICKLINK_CONSUMER_KEY and not REBRICKABLE_API_KEY:
        return [], list(new_element_ids)
    resolved: list[tuple[int, str, int, str]] = []
    unresolved: list[int] = []
    values = []
    for i, element_id in enumerate(new_element_ids):
        source = "bricklink"
        part_name = None
        mapping = fetch_bl_item_mapping(element_id)
        if not mapping:
            rb = fetch_rebrickable_mapping(element_id)
            if rb:
                part_no, bl_color_id, part_name = rb
                mapping = {"part_no": part_no, "color_id": bl_color_id, "item_type": "PART"}
                source = "rebrickable"

        if mapping:
            values.append((
                element_id, mapping["part_no"], mapping["color_id"],
                mapping["item_type"], part_name, source, now,
            ))
            resolved.append((element_id, mapping["part_no"], mapping["color_id"], source))
        else:
            unresolved.append(element_id)
        if i < len(new_element_ids) - 1:
            time.sleep(1)  # polite pacing — this only runs for a handful of new elements/day
    if values:
        psycopg2.extras.execute_values(cur, INSERT_BL_MAPPING_NEW_ONLY, values, page_size=100)
    return resolved, unresolved


def send_enrichment_report(resolved: list[tuple[int, str, int, str]], unresolved: list[int]) -> None:
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "noreply@vaultcrest.com")
    report_email  = os.environ.get("REPORT_EMAIL", "")
    if not smtp_host or not report_email:
        return

    total = len(resolved) + len(unresolved)
    bl_count = sum(1 for *_, source in resolved if source == "bricklink")
    rb_count = len(resolved) - bl_count
    subject = f"Enrichment needed: {total} new PAB element(s), {len(resolved)} resolved"
    lines = [
        f"New PAB elements seen this run : {total}",
        f"Resolved via BrickLink          : {bl_count}",
        f"Resolved via Rebrickable         : {rb_count}",
        f"Unresolved (no mapping yet)      : {len(unresolved)}",
        "",
    ]
    if resolved:
        lines.append("Resolved:")
        lines += [f"  • {eid} -> BL part {part_no} / color {color_id} [{source}]" for eid, part_no, color_id, source in resolved]
        lines.append("")
    if unresolved:
        lines.append("Unresolved — needs manual mapping, or neither source has this part yet:")
        lines += [f"  • {eid}" for eid in unresolved]

    msg = MIMEText("\n".join(lines))
    msg["Subject"] = f"[MOC Source] {subject}"
    msg["From"]    = smtp_from
    msg["To"]      = report_email
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(smtp_from, [report_email], msg.as_string())
        print(f"Enrichment report emailed to {report_email}", flush=True)
    except Exception as e:
        print(f"Failed to send enrichment report email: {e}", file=sys.stderr)


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


# ─── Cloudflare cache purge ──────────────────────────────────────────────────

def purge_cf_cache() -> None:
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    token   = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not zone_id or not token:
        return
    import json as _json
    import urllib.request
    url     = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
    payload = _json.dumps({"purge_everything": True}).encode()
    req     = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
        if result.get("success"):
            print("Cloudflare cache purged.", flush=True)
        else:
            print(f"CF purge failed: {result.get('errors')}", flush=True)
    except Exception as e:
        print(f"CF purge error: {e}", flush=True)


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


_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pab_locale_idx")


def main():
    parser = argparse.ArgumentParser(description="Scrape PAB inventory to PostgreSQL")
    parser.add_argument("--locale", help="Scrape a single locale only (e.g. en-us)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write to DB")
    parser.add_argument(
        "--mode", choices=["full", "oos"], default="full",
        help="full: all locales, prices + availability. "
             "oos: 3 representative locales only, propagates in_stock to sibling locales (hourly).",
    )
    parser.add_argument(
        "--one-locale", action="store_true",
        help="Round-robin: pick one locale per invocation using a state file. "
             "Pair with --mode full and an hourly timer to spread the full price "
             "refresh across the day (one locale per hour, ~18 hours per cycle).",
    )
    args = parser.parse_args()

    if args.mode == "oos":
        locales = OOS_LOCALES
    elif args.one_locale:
        try:
            idx = int(open(_STATE_FILE).read().strip())
        except (FileNotFoundError, ValueError):
            idx = 0
        locales = [LOCALES[idx % len(LOCALES)]]
        next_idx = (idx + 1) % len(LOCALES)
        try:
            open(_STATE_FILE, "w").write(str(next_idx))
        except Exception as e:
            print(f"Warning: could not write state file: {e}", file=sys.stderr)
        print(f"Round-robin: locale {idx % len(LOCALES) + 1}/{len(LOCALES)} → {locales[0]}", flush=True)
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
                raw, cached_ids, scan_complete = fetch_locale(
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
                        # Determine which elements are brand new before upserting, so we
                        # know which ones need BL mapping resolution via Rebrickable.
                        incoming_ids = [r["element_id"] for r in rows]
                        cur.execute(
                            "SELECT element_id FROM lego_elements WHERE element_id = ANY(%s)",
                            (incoming_ids,),
                        )
                        existing_ids = {row[0] for row in cur.fetchall()}
                        new_ids = [eid for eid in incoming_ids if eid not in existing_ids]

                        # Full upsert: updates pricing + channel on existing rows,
                        # and creates any brand-new elements LEGO has added since last seed.
                        # Skipped in OOS mode — channel data is refreshed by the daily full run.
                        n2 = write_elements_en_us(cur, rows, now)
                        total_elements += n2
                        print(f"  [{locale}] upserted {n2} lego_elements rows", flush=True)

                        if new_ids:
                            resolved, unresolved = enrich_new_elements(cur, new_ids, now)
                            print(
                                f"  [{locale}] resolved BL mapping for {len(resolved)}/{len(new_ids)} "
                                "new elements via Rebrickable",
                                flush=True,
                            )
                            send_enrichment_report(resolved, unresolved)
                    else:
                        # Refresh updated_at for known elements, insert new ones.
                        # Keeps the stale-element check accurate across all locales.
                        ensure_elements_exist(cur, rows, now)

                    n = write_prices(cur, rows)
                    total_prices += n

                    # Stale detection: only when the scan was complete (all pages and
                    # sibling batches succeeded). A partial scan would falsely mark
                    # unseen elements as OOS. OOS mode never runs stale detection
                    # since it intentionally fetches only a partial catalog.
                    if args.mode == "full" and scan_complete:
                        cur.execute(MARK_STALE_PRICES_OOS, {"now": now, "locale": locale, "run_start": locale_start})
                        stale_p = cur.rowcount
                        if stale_p:
                            print(f"  [{locale}] {stale_p} price rows marked out-of-stock (left catalog)", flush=True)
                    elif args.mode == "full" and not scan_complete:
                        print(f"  [{locale}] scan incomplete — skipping stale detection to avoid false OOS", flush=True)

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
        purge_cf_cache()


if __name__ == "__main__":
    main()
