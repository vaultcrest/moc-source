"""Minimal BrickLink Catalog API client using OAuth 1.0a (stdlib only)."""

import asyncio
import base64
import hashlib
import hmac
import time
import urllib.parse
import uuid

import requests

from .config import settings

BL_API_BASE = "https://api.bricklink.com/api/store/v1"


def _oauth1_header(method: str, url: str) -> str:
    ck = settings.bricklink_consumer_key
    cs = settings.bricklink_consumer_secret
    tk = settings.bricklink_token
    ts = settings.bricklink_token_secret

    params = {
        "oauth_consumer_key":     ck,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            tk,
        "oauth_version":          "1.0",
    }

    enc = urllib.parse.quote
    param_string = "&".join(
        f"{enc(k, safe='')}={enc(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base_string = "&".join([
        method.upper(),
        enc(url, safe=""),
        enc(param_string, safe=""),
    ])
    signing_key = enc(cs, safe="") + "&" + enc(ts, safe="")
    sig = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    params["oauth_signature"] = base64.b64encode(sig).decode()

    return "OAuth " + ", ".join(
        f'{enc(k, safe="")}="{enc(v, safe="")}"'
        for k, v in sorted(params.items())
    )


def _fetch_part_sync(part_no: str) -> dict | None:
    url = f"{BL_API_BASE}/items/PART/{urllib.parse.quote(part_no, safe='')}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": _oauth1_header("GET", url)},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data")
        if not data:
            return None
        raw_alt = data.get("alternate_no") or ""
        if isinstance(raw_alt, str):
            alternates = [p.strip() for p in raw_alt.split(",") if p.strip()]
        else:
            alternates = [str(p).strip() for p in raw_alt if str(p).strip()]
        return {
            "name": data.get("name"),
            "item_type": data.get("type"),
            "alternate_no": alternates,
        }
    except Exception:
        return None


async def fetch_bl_part(part_no: str) -> dict | None:
    """Async wrapper — runs the sync BL HTTP call in a thread pool."""
    if not settings.bricklink_consumer_key:
        return None
    return await asyncio.to_thread(_fetch_part_sync, part_no)
