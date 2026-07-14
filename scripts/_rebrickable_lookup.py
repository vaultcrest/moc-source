"""Shared Rebrickable -> BrickLink part-number resolution helpers.

Used by scripts/scrape_pab.py, scripts/import_rebrickable.py,
scripts/fix_rebrickable_part_nos.py, and scripts/backfill_last_used_year.py.
Rebrickable's own part_num values (e.g. "27372pr0006") are NOT BrickLink
part numbers and must never be written into bricklink_mappings.part_no
directly or derived via string transform — the translation only exists in
external_ids.BrickLink on Rebrickable's part/element resources. Confirmed
empirically (2026-07-14): base numbers can differ entirely between the two
systems (Rebrickable "102220pr0001" -> BrickLink "47205pb098"), so this must
always be a live lookup, never a regex.

Three entry points:
  resolve_bl_part_nos_bulk()      -- efficient, up to 100 part_nums/call
  resolve_part_years_bulk()       -- same bulk endpoint, year_from/year_to
                                      instead of the BrickLink translation
  resolve_element_via_rebrickable() -- per-element_id fallback for stale/
                                        renumbered part_nums the bulk calls
                                        miss (Rebrickable sometimes
                                        renumbers print variants; the
                                        element_id stays stable)

All retry on HTTP 429 honoring Retry-After, and the caller is expected to
pace at >=1.2s between calls to stay under Rebrickable's stated 1 req/sec
average limit (this module does not sleep between its own internal chunk
calls beyond what's needed for a single logical resolve, so callers doing
many resolves in a loop must add their own inter-call delay).
"""
import time

import requests

REBRICKABLE_API_BASE = "https://rebrickable.com/api/v3/lego"
# Rebrickable's bulk parts endpoint silently truncates results beyond this
# many part_nums per call (confirmed empirically: a 200-part_num request
# returned only 100 results, no error) -- so this is a hard ceiling, not a
# tunable preference.
MAX_PART_NUMS_PER_CALL = 100
DEFAULT_RETRY_AFTER = 5.0


def _get_with_retry(url: str, params: dict, headers: dict, max_retries: int = 3):
    """GET with 429 retry honoring Retry-After. Returns Response, or None if
    retries were exhausted or a network error occurred."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=25)
        except requests.exceptions.RequestException as e:
            print(f"  Rebrickable network error for {url}: {e}", flush=True)
            return None
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else DEFAULT_RETRY_AFTER
            except ValueError:
                delay = DEFAULT_RETRY_AFTER
            print(f"  Rebrickable 429 rate-limited (attempt {attempt + 1}/{max_retries}), "
                  f"Retry-After={delay}s: {url}", flush=True)
            time.sleep(delay)
            continue
        return resp
    print(f"  Rebrickable 429 retries exhausted for {url}", flush=True)
    return None


def resolve_bl_part_nos_bulk(part_nums: list[str], api_key: str, inter_call_delay: float = 1.2) -> dict[str, str]:
    """Resolve many Rebrickable part_nums to BrickLink part numbers in one pass.

    Returns {rebrickable_part_num: bl_part_no} for whatever resolved. A
    part_num missing from the result means Rebrickable had no BrickLink
    translation for it (or no record at all) via this endpoint -- try
    resolve_element_via_rebrickable() as a fallback, since a stored
    part_num string can go stale if Rebrickable renumbers the variant.
    """
    if not api_key or not part_nums:
        return {}
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    url = f"{REBRICKABLE_API_BASE}/parts/"
    resolved: dict[str, str] = {}
    for i in range(0, len(part_nums), MAX_PART_NUMS_PER_CALL):
        chunk = part_nums[i : i + MAX_PART_NUMS_PER_CALL]
        params = {"part_nums": ",".join(chunk), "inc_part_details": 1}
        resp = _get_with_retry(url, params, headers)
        if resp is None or resp.status_code != 200:
            continue
        for result in resp.json().get("results", []):
            bl_ids = (result.get("external_ids") or {}).get("BrickLink") or []
            if bl_ids:
                resolved[result["part_num"]] = bl_ids[0]
        if i + MAX_PART_NUMS_PER_CALL < len(part_nums):
            time.sleep(inter_call_delay)
    return resolved


def resolve_part_years_bulk(
    part_nums: list[str], api_key: str, inter_call_delay: float = 1.2
) -> dict[str, tuple[int | None, int | None]]:
    """Resolve many Rebrickable part_nums to (year_from, year_to) in one pass.

    year_from/year_to are Rebrickable's own first-year/last-year-used fields,
    returned by the same bulk parts endpoint used by resolve_bl_part_nos_bulk
    -- confirmed live 2026-07-14 (part 3001 -> year_from=1979, year_to=2026).
    A part_num missing from the result means Rebrickable had no record for it
    via this endpoint.
    """
    if not api_key or not part_nums:
        return {}
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    url = f"{REBRICKABLE_API_BASE}/parts/"
    resolved: dict[str, tuple[int | None, int | None]] = {}
    for i in range(0, len(part_nums), MAX_PART_NUMS_PER_CALL):
        chunk = part_nums[i : i + MAX_PART_NUMS_PER_CALL]
        params = {"part_nums": ",".join(chunk), "inc_part_details": 1}
        resp = _get_with_retry(url, params, headers)
        if resp is None or resp.status_code != 200:
            continue
        for result in resp.json().get("results", []):
            resolved[result["part_num"]] = (result.get("year_from"), result.get("year_to"))
        if i + MAX_PART_NUMS_PER_CALL < len(part_nums):
            time.sleep(inter_call_delay)
    return resolved


def resolve_element_via_rebrickable(element_id: int, api_key: str) -> dict | None:
    """Fetch full element resolution info from Rebrickable's /lego/elements/{id}/.

    Returns a dict with:
      part_num    -- Rebrickable's CURRENT part_num for this element (may
                      differ from a previously-stored value if Rebrickable
                      renumbered/consolidated the print variant since)
      part_name   -- Rebrickable's part name, or None
      bl_part_no  -- BrickLink part number (str), or None if untranslated
      bl_color_id -- BrickLink color id (int), or None if untranslated
    or None if the element itself wasn't found / the request failed.
    """
    if not api_key:
        return None
    url = f"{REBRICKABLE_API_BASE}/elements/{element_id}/"
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    resp = _get_with_retry(url, {}, headers)
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    part = data.get("part") or {}
    color = data.get("color") or {}
    bl_part_ids = (part.get("external_ids") or {}).get("BrickLink") or []
    bl_color_ids = ((color.get("external_ids") or {}).get("BrickLink") or {}).get("ext_ids") or []
    return {
        "part_num": part.get("part_num"),
        "part_name": part.get("name"),
        "bl_part_no": bl_part_ids[0] if bl_part_ids else None,
        "bl_color_id": int(bl_color_ids[0]) if bl_color_ids else None,
    }
