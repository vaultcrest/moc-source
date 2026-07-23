"""Shared BrickLink OAuth1-signed catalog lookup helpers.

Used by scripts/scrape_bl_mold_data.py. Extracted 2026-07-14 so BrickLink
scripts share one OAuth-signing/retry implementation instead of maintaining
duplicate copies.

BLClient bundles the four BrickLink OAuth1 credentials once and exposes:
  fetch_item(item_type, no)  -- catalog detail for any item type (PART, SET,
                                 MINIFIG, ...): name, item_type, year_released,
                                 alternate_no (when present)
  fetch_subsets(set_no)      -- a SET's MINIFIG-typed subset entries
                                 (no, name, quantity); used for fig_num <->
                                 minifig_no mapping (2026-07-23, see
                                 scripts/map_rebrickable_minifigs.py)

Retries on network errors / 429 / 5xx (3 attempts, exponential backoff),
mirroring the retry contract already established in scrape_bl_mold_data.py:
returns (attempted, data) where attempted=False means retries were exhausted
and the caller should not persist anything (leave it for a future run).
"""
import base64
import hashlib
import hmac
import sys
import time
import urllib.parse
import uuid

import requests

BL_API_BASE = "https://api.bricklink.com/api/store/v1"


class BLClient:
    def __init__(self, consumer_key: str, consumer_secret: str, token: str, token_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token = token
        self.token_secret = token_secret

    def _oauth1_header(self, method: str, url: str) -> str:
        # OAuth1 requires every query-string param (not just oauth_* ones) in
        # the signature base string, sorted together -- fetch_item/fetch_colors
        # never hit this since their URLs carry no query string, but
        # fetch_price_guide's does (color_id/guide_type/new_or_used/region).
        parsed = urllib.parse.urlsplit(url)
        base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        query_params = dict(urllib.parse.parse_qsl(parsed.query))

        oauth_params = {
            "oauth_consumer_key":     self.consumer_key,
            "oauth_nonce":            uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp":        str(int(time.time())),
            "oauth_token":            self.token,
            "oauth_version":          "1.0",
        }
        enc = urllib.parse.quote
        all_params = {**query_params, **oauth_params}
        param_string = "&".join(f"{enc(k, safe='')}={enc(v, safe='')}" for k, v in sorted(all_params.items()))
        base_string = "&".join([method.upper(), enc(base_url, safe=""), enc(param_string, safe="")])
        signing_key = enc(self.consumer_secret, safe="") + "&" + enc(self.token_secret, safe="")
        sig = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        oauth_params["oauth_signature"] = base64.b64encode(sig).decode()
        return "OAuth " + ", ".join(f'{enc(k, safe="")}="{enc(v, safe="")}"' for k, v in sorted(oauth_params.items()))

    def _get(self, url: str, label: str, identifier: str):
        """Shared retry loop. Returns (attempted, resp_or_none).

        attempted=True means BL gave an authoritative answer (200, or a 4xx
        that isn't 429) -- the caller should persist state regardless of
        whether any data came back. attempted=False means a transient
        failure (network error, 429, 5xx) exhausted its retries -- the
        caller must not write anything, so a future run retries this item.
        """
        for attempt in range(3):
            try:
                resp = requests.get(url, headers={"Authorization": self._oauth1_header("GET", url)}, timeout=8)
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    print(f"  BL {label} network failure for {identifier}: {e}", file=sys.stderr)
                    return False, None
                time.sleep(2 * (attempt + 1))
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 2:
                    print(f"  BL {label} rate-limited/server error for {identifier}: HTTP {resp.status_code}",
                          file=sys.stderr)
                    return False, None
                time.sleep(2 * (attempt + 1))
                continue

            return True, resp
        return False, None

    def fetch_item(self, item_type: str, no: str) -> tuple[bool, dict | None]:
        """Fetch (name, item_type, alternate_no, year_released, category_id)
        for any BL item type. Mirrors the parsing in mocsource/bl_client.py's
        _fetch_part_sync (PART-specific there; this generalizes to any type).
        category_id is BrickLink's own catalog category (see bl_categories /
        scripts/seed_bl_categories.py) -- not scoped to any one item type by
        BrickLink itself, so a category_id seen here isn't guaranteed to be
        one of bl_categories' part-only rows."""
        url = f"{BL_API_BASE}/items/{item_type}/{urllib.parse.quote(no, safe='')}"
        attempted, resp = self._get(url, f"{item_type} catalog", no)
        if not attempted:
            return False, None
        if resp.status_code == 404:
            return True, None
        if resp.status_code != 200:
            print(f"  BL {item_type} catalog unexpected status for {no}: HTTP {resp.status_code}", file=sys.stderr)
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
            "category_id": data.get("category_id"),
        }

    def fetch_price_guide(self, part_no: str, color_id: int, new_or_used: str) -> tuple[bool, dict | None]:
        """Fetch BrickLink's Price Guide (sold, worldwide) for one
        (part_no, color_id, new_or_used) combo. No region param -- confirmed
        live 2026-07-15 that BrickLink's region filter is a genuine
        server-side restriction, not something we need to (or should)
        replicate client-side; dropping it returns the full worldwide
        price_detail[] in the same single call, which the caller buckets
        into global/north_america/eu_gb/other itself (scripts/_price_guide_
        regions.py) -- more regional granularity at no extra API cost.
        Returns BL's raw {min_price, max_price, avg_price, qty_avg_price,
        unit_quantity, total_quantity, price_detail: [...]}; price_detail
        rows carry quantity, unit_price, seller_country_code,
        buyer_country_code, date_ordered. Rows can span back years, but are
        only dense/reliable for roughly the most recent 6 full calendar
        months -- older than that gets sporadic (single anecdotal sales,
        whole months missing); scrape_bl_price_guide.py enforces a 6-month
        retention floor (month_floor_minus()) for this reason. new_or_used
        is 'N' or 'U'. A 404 means BL has no sold data for this combo at all
        (not an error)."""
        url = (f"{BL_API_BASE}/items/PART/{urllib.parse.quote(part_no, safe='')}/price"
               f"?color_id={color_id}&guide_type=sold&new_or_used={new_or_used}")
        attempted, resp = self._get(url, "price guide", f"{part_no}/{color_id}/{new_or_used}")
        if not attempted:
            return False, None
        if resp.status_code == 404:
            return True, None
        if resp.status_code != 200:
            print(f"  BL price guide unexpected status for {part_no}/{color_id}/{new_or_used}: "
                  f"HTTP {resp.status_code}", file=sys.stderr)
            return True, None
        return True, resp.json().get("data") or None

    def fetch_subsets(self, set_no: str) -> tuple[bool, list[dict] | None]:
        """Fetch a SET's subset breakdown (GET /items/SET/{no}/subsets) and
        return only its MINIFIG-typed entries, flattened out of BL's nested
        match_no/entries[] structure: [{no, name, quantity}, ...]. Used by
        scripts/map_rebrickable_minifigs.py to cross-reference against
        Rebrickable's inventory_minifigs.csv (which shares set_num with BL,
        unlike minifig numbering itself -- see that script's docstring).
        A 404 means BL has no subset breakdown for this set (not an error)."""
        url = f"{BL_API_BASE}/items/SET/{urllib.parse.quote(set_no, safe='')}/subsets"
        attempted, resp = self._get(url, "subsets", set_no)
        if not attempted:
            return False, None
        if resp.status_code == 404:
            return True, []
        if resp.status_code != 200:
            print(f"  BL subsets unexpected status for {set_no}: HTTP {resp.status_code}", file=sys.stderr)
            return True, []

        minifigs = []
        for group in resp.json().get("data") or []:
            for entry in group.get("entries") or []:
                item = entry.get("item") or {}
                if item.get("type") != "MINIFIG":
                    continue
                minifigs.append({
                    "no": item.get("no"),
                    "name": item.get("name"),
                    "quantity": entry.get("quantity", 0),
                })
        return True, minifigs

    def fetch_colors(self) -> tuple[bool, list[dict] | None]:
        """Fetch BrickLink's full colors catalog: list of {color_id, color_name,
        color_code, color_type}, ~214 entries as of 2026-07-14. One call, no
        pagination — unlike fetch_item(), this is a bulk list endpoint."""
        url = f"{BL_API_BASE}/colors"
        attempted, resp = self._get(url, "colors catalog", "all")
        if not attempted:
            return False, None
        if resp.status_code != 200:
            print(f"  BL colors catalog unexpected status: HTTP {resp.status_code}", file=sys.stderr)
            return True, None
        return True, resp.json().get("data") or []
