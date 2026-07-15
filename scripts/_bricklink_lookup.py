"""Shared BrickLink OAuth1-signed catalog lookup helpers.

Used by scripts/scrape_bl_mold_data.py. Extracted 2026-07-14 so BrickLink
scripts share one OAuth-signing/retry implementation instead of maintaining
duplicate copies.

BLClient bundles the four BrickLink OAuth1 credentials once and exposes:
  fetch_item(item_type, no)  -- catalog detail for any item type (PART, SET,
                                 MINIFIG, ...): name, item_type, year_released,
                                 alternate_no (when present)

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
        params = {
            "oauth_consumer_key":     self.consumer_key,
            "oauth_nonce":            uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp":        str(int(time.time())),
            "oauth_token":            self.token,
            "oauth_version":          "1.0",
        }
        enc = urllib.parse.quote
        param_string = "&".join(f"{enc(k, safe='')}={enc(v, safe='')}" for k, v in sorted(params.items()))
        base_string = "&".join([method.upper(), enc(url, safe=""), enc(param_string, safe="")])
        signing_key = enc(self.consumer_secret, safe="") + "&" + enc(self.token_secret, safe="")
        sig = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        params["oauth_signature"] = base64.b64encode(sig).decode()
        return "OAuth " + ", ".join(f'{enc(k, safe="")}="{enc(v, safe="")}"' for k, v in sorted(params.items()))

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
        """Fetch (name, item_type, alternate_no, year_released) for any BL
        item type. Mirrors the parsing in mocsource/bl_client.py's
        _fetch_part_sync (PART-specific there; this generalizes to any type)."""
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
        }

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
