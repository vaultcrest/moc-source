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

Five entry points:
  resolve_bl_part_nos_bulk()      -- efficient, chunked to stay under
                                      MAX_URL_LENGTH per call (up to 1,000
                                      part_nums/call, fewer if they're long)
  resolve_part_years_bulk()       -- same bulk endpoint, year_from/year_to
                                      instead of the BrickLink translation
  resolve_element_via_rebrickable() -- per-element_id fallback for stale/
                                        renumbered part_nums the bulk calls
                                        miss (Rebrickable sometimes
                                        renumbers print variants; the
                                        element_id stays stable)
  resolve_bl_part_no_reverse()    -- opposite direction: given a real
                                      BrickLink part_no with zero known
                                      Rebrickable mapping at all, find
                                      Rebrickable's part_num for it (or None)
  resolve_part_colors_elements()  -- given a Rebrickable part_num, list its
                                      known element_ids per color (pairs with
                                      resolve_bl_part_no_reverse() to turn a
                                      reverse-lookup match into real,
                                      element_id-keyed bricklink_mappings rows)

All retry on HTTP 429 honoring Retry-After, and the caller is expected to
pace at >=1.2s between calls to stay under Rebrickable's stated 1 req/sec
average limit (this module does not sleep between its own internal chunk
calls beyond what's needed for a single logical resolve, so callers doing
many resolves in a loop must add their own inter-call delay).
"""
import time

import requests

REBRICKABLE_API_BASE = "https://rebrickable.com/api/v3/lego"
# The bulk parts endpoint's default page_size is 100 -- a request with more
# part_nums than that silently returns only the first page, no error (this
# was previously mistaken for a hard ceiling on the endpoint itself). Passing
# page_size explicitly raises that: confirmed live 2026-07-21, 1,000 part_nums
# + page_size=1000 returned all 851 real matches in one call, no pagination.
#
# BUT batching by a fixed item count alone isn't safe: part_num string length
# varies a lot (short like "3639" vs long print-variant codes like
# "973pb1782c01"), so a 1,000-item chunk's real URL length can swing wildly
# depending on content -- confirmed live 2026-07-21, chunks of the same
# nominal size ranged from url_len=8,565 to url_len=16,044 chars in a single
# real run. Some intermediate proxy/edge (not Rebrickable's own backend --
# the failure was instant, ~0.2s, not a timeout) rejects requests past some
# undocumented length with an HTTP 520, no error detail. Reproduced directly:
# the exact same 1,000-item chunk (url_len=16,044) failed every time, split
# into two ~8,065-char halves both succeeded. A 13,616-char chunk succeeded
# elsewhere in the same run, so the real cutoff sits somewhere in
# 13.6-15.3KB -- MAX_URL_LENGTH below stays well under that with margin.
# So chunking is by character budget, not item count; MAX_PART_NUMS_PER_CALL
# is now just the per-call ceiling used for page_size (must be >= the
# largest chunk _chunk_by_length can produce, which it always is since that
# function's char budget caps a chunk at far fewer than 1,000 items whenever
# individual part_nums are unusually long).
MAX_PART_NUMS_PER_CALL = 1000
MAX_URL_LENGTH = 10000
DEFAULT_RETRY_AFTER = 5.0


def _chunk_by_length(
    items: list[str], base_overhead: int, max_chars: int = MAX_URL_LENGTH,
    max_items: int = MAX_PART_NUMS_PER_CALL,
) -> list[list[str]]:
    """Group items into chunks whose comma-joined length (plus base_overhead
    for the URL/other params) stays under max_chars, AND whose item count
    stays under max_items. Both caps are required: for short part_nums the
    character budget alone permits well over 1,000 items per chunk (short
    numeric strings like "4429" pack tight), but page_size gets sent as
    min(chunk_size, MAX_PART_NUMS_PER_CALL) -- an uncapped chunk bigger than
    that silently re-triggers the exact page_size truncation this module
    already had to fix once (see MAX_PART_NUMS_PER_CALL's comment), just via
    a different trigger. Confirmed live 2026-07-21: this exact gap silently
    dropped a reproducible 812 real parts (rechecked twice, identical both
    times, zero HTTP errors either time -- the request itself looked fine,
    Rebrickable just never got asked about the truncated tail)."""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = base_overhead
    for item in items:
        added = len(item) + (1 if current else 0)  # +1 for the joining comma
        if current and (current_chars + added > max_chars or len(current) >= max_items):
            chunks.append(current)
            current = []
            current_chars = base_overhead
            added = len(item)
        current.append(item)
        current_chars += added
    if current:
        chunks.append(current)
    return chunks


def _get_with_retry(url: str, params: dict, headers: dict, max_retries: int = 3):
    """GET with retry on 429 (honoring Retry-After) and on transient 5xx/network
    errors (fixed backoff) -- confirmed live 2026-07-21: switching the bulk
    parts endpoint to 1,000-item batches (page_size bump) hit a run of
    Cloudflare 520s ("Web Server Returned an Unknown Error") across 6
    consecutive chunks. Previously only 429 was retried, so each of those
    chunks was silently abandoned with zero retry -- costing ~1,000 unresolved
    part_nums per failed chunk instead of ~100, since bigger batches raise the
    stakes of any single request failing. Returns Response, or None if
    retries were exhausted or every attempt hit a network error."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=25)
        except requests.exceptions.RequestException as e:
            print(f"  Rebrickable network error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_AFTER)
                continue
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
        if 500 <= resp.status_code < 600:
            print(f"  Rebrickable {resp.status_code} server error (attempt {attempt + 1}/{max_retries}): {url}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_AFTER)
                continue
            return resp
        return resp
    print(f"  Rebrickable retries exhausted for {url}", flush=True)
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
    base_overhead = len(url) + len("?part_nums=&inc_part_details=1&page_size=1000")
    chunks = _chunk_by_length(part_nums, base_overhead)
    resolved: dict[str, str] = {}
    for i, chunk in enumerate(chunks):
        params = {"part_nums": ",".join(chunk), "inc_part_details": 1, "page_size": min(len(chunk), MAX_PART_NUMS_PER_CALL)}
        resp = _get_with_retry(url, params, headers)
        if resp is None or resp.status_code != 200:
            continue
        for result in resp.json().get("results", []):
            bl_ids = (result.get("external_ids") or {}).get("BrickLink") or []
            if bl_ids:
                resolved[result["part_num"]] = bl_ids[0]
        if i + 1 < len(chunks):
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
    base_overhead = len(url) + len("?part_nums=&inc_part_details=1&page_size=1000")
    chunks = _chunk_by_length(part_nums, base_overhead)
    resolved: dict[str, tuple[int | None, int | None]] = {}
    for i, chunk in enumerate(chunks):
        params = {"part_nums": ",".join(chunk), "inc_part_details": 1, "page_size": min(len(chunk), MAX_PART_NUMS_PER_CALL)}
        resp = _get_with_retry(url, params, headers)
        if resp is None or resp.status_code != 200:
            continue
        for result in resp.json().get("results", []):
            resolved[result["part_num"]] = (result.get("year_from"), result.get("year_to"))
        if i + 1 < len(chunks):
            time.sleep(inter_call_delay)
    return resolved


def resolve_element_via_rebrickable(element_id: int, api_key: str) -> dict | None:
    """Fetch full element resolution info from Rebrickable's /lego/elements/{id}/.

    Returns a dict with:
      part_num    -- Rebrickable's CURRENT part_num for this element (may
                      differ from a previously-stored value if Rebrickable
                      renumbered/consolidated the print variant since)
      part_name   -- Rebrickable's part name, or None
      design_id   -- Rebrickable's design_id for this element (top-level
                      field on the response, not part.*) -- lego_elements'
                      own PK-adjacent column, required alongside element_id
                      by bricklink_mappings' FK to lego_elements
      year_from   -- Rebrickable's first-year-used for this part, or None
      year_to     -- Rebrickable's last-year-used for this part, or None
      bl_part_no  -- BrickLink part number (str), or None if untranslated
      bl_color_id -- BrickLink color id (int), or None if untranslated
    or None if the element itself wasn't found / the request failed.

    year_from/year_to come free in this same response (confirmed live
    2026-07-21) -- useful when a stored part_num 404s against the bulk
    /parts/ endpoint because Rebrickable renumbered it since our local
    elements.csv snapshot was taken (element_id stays stable across
    renumbering, so this is the reliable path when that happens).
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
        "design_id": data.get("design_id"),
        "year_from": part.get("year_from"),
        "year_to": part.get("year_to"),
        "bl_part_no": bl_part_ids[0] if bl_part_ids else None,
        "bl_color_id": int(bl_color_ids[0]) if bl_color_ids else None,
    }


def resolve_bl_part_no_reverse(bl_part_no: str, api_key: str) -> str | None:
    """Given a real BrickLink part_no with zero bricklink_mappings row at
    all, find Rebrickable's own part_num for it via the bulk /parts/
    endpoint's bricklink_id= filter -- the reverse direction from every
    other function here, all of which start from a Rebrickable part_num.

    bricklink_id= is undocumented but real and exact-match, confirmed live
    2026-07-21 against 5 real never-mapped part_nos, all correct
    (cross-checked external_ids.BrickLink on each result contained exactly
    the queried value). It's single-value only -- comma-joining multiple
    part_nos returns 0 results, and repeated query-string keys only honor
    the last one (Django's request.GET.get() behavior) -- so this is always
    one API call per part_no, no bulk form exists.

    Returns the matched Rebrickable part_num, or None if Rebrickable has no
    record under any numbering for this BrickLink part at all.
    """
    if not api_key or not bl_part_no:
        return None
    url = f"{REBRICKABLE_API_BASE}/parts/"
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    resp = _get_with_retry(url, {"bricklink_id": bl_part_no, "inc_part_details": 1}, headers)
    if resp is None or resp.status_code != 200:
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    return results[0].get("part_num")


def resolve_part_colors_elements(rb_part_num: str, api_key: str) -> list[int]:
    """Given a Rebrickable part_num, return every known element_id across
    all its colors via /lego/parts/{part_num}/colors/.

    A part can legitimately have zero elements for some or all colors --
    confirmed live 2026-07-21 on an obscure 1980-81 electric part
    (266ac01), which returned one color with an empty elements list. That's
    real "no element data tracked" for that part+color, not an error -- a
    well-populated part (e.g. 3001) returns real element_ids per color.
    """
    if not api_key or not rb_part_num:
        return []
    url = f"{REBRICKABLE_API_BASE}/parts/{rb_part_num}/colors/"
    headers = {"Authorization": f"key {api_key}", "User-Agent": "mocsource/1.0"}
    resp = _get_with_retry(url, {}, headers)
    if resp is None or resp.status_code != 200:
        return []
    element_ids: list[int] = []
    for result in resp.json().get("results", []):
        for eid in result.get("elements") or []:
            try:
                element_ids.append(int(eid))
            except (TypeError, ValueError):
                pass
    return element_ids
