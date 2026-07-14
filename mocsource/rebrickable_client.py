"""Rebrickable API client — BL color mapping and element lookup."""

import asyncio
import logging
import urllib.parse

import requests

from .config import settings

log = logging.getLogger(__name__)

_RB_BASE = "https://rebrickable.com/api/v3/lego"

# Process-level cache: BrickLink color_id (int) → Rebrickable color_id (int)
_bl_to_rb_color: dict[int, int] | None = None


def _fetch_color_map_sync() -> dict[int, int]:
    api_key = settings.rebrickable_api_key
    if not api_key:
        return {}
    mapping: dict[int, int] = {}
    url = f"{_RB_BASE}/colors/?key={api_key}&page_size=300"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "mocsource/1.0"})
        if resp.status_code != 200:
            log.warning("Rebrickable color map returned HTTP %s", resp.status_code)
            return {}
        for color in resp.json().get("results", []):
            rb_id = color["id"]
            bl_ids = color.get("external_ids", {}).get("BrickLink", {}).get("ext_ids", [])
            for bl_id in bl_ids:
                mapping[int(bl_id)] = rb_id
        log.info("Rebrickable color map loaded: %d BL colors mapped", len(mapping))
    except Exception as e:
        log.warning("Rebrickable color map fetch failed: %s", e)
    return mapping


async def get_bl_to_rb_color_map() -> dict[int, int]:
    """Return cached BL color_id → Rebrickable color_id mapping (fetched once per process)."""
    global _bl_to_rb_color
    if _bl_to_rb_color is None:
        _bl_to_rb_color = await asyncio.to_thread(_fetch_color_map_sync)
    return _bl_to_rb_color


def _fetch_elements_for_part_color_sync(part_no: str, rb_color_id: int) -> list[int]:
    """Return LEGO element IDs for a Rebrickable part_no at rb_color_id. Empty list if not found."""
    api_key = settings.rebrickable_api_key
    if not api_key:
        return []
    encoded = urllib.parse.quote(part_no, safe="")
    url = f"{_RB_BASE}/parts/{encoded}/colors/{rb_color_id}/?key={api_key}"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "mocsource/1.0"})
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            log.warning("Rebrickable parts/colors returned HTTP %s for %s/%s", resp.status_code, part_no, rb_color_id)
            return []
        elements = resp.json().get("elements", [])
        return [int(e) for e in elements if str(e).isdigit()]
    except Exception as e:
        log.warning("Rebrickable element lookup failed (%s / rb_color=%s): %s", part_no, rb_color_id, e)
        return []


async def find_elements(
    part_no: str,
    alternates: list[str],
    rb_color_id: int,
) -> tuple[str, list[int]]:
    """Try part_no, then each alternate, until Rebrickable returns element IDs.

    Returns (resolved_part_no, element_ids) or ("", []) if nothing found.
    """
    for candidate in [part_no] + alternates:
        elements = await asyncio.to_thread(_fetch_elements_for_part_color_sync, candidate, rb_color_id)
        if elements:
            log.info("Rebrickable resolved %s via %s → %d elements", part_no, candidate, len(elements))
            return candidate, elements
    return "", []


def _fetch_element_mapping_sync(element_id: int) -> tuple[str, int, str | None] | None:
    """Return (bl_part_no, bl_color_id, part_name) for a LEGO element_id, or None if not found."""
    api_key = settings.rebrickable_api_key
    if not api_key:
        return None
    url = f"{_RB_BASE}/elements/{element_id}/?key={api_key}"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "mocsource/1.0"})
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            log.warning("Rebrickable element lookup returned HTTP %s for element %s", resp.status_code, element_id)
            return None
        data = resp.json()
        part = data.get("part") or {}
        part_name = part.get("name")
        bl_part_ids = (part.get("external_ids") or {}).get("BrickLink") or []
        bl_color_ids = (
            ((data.get("color") or {}).get("external_ids") or {})
            .get("BrickLink", {})
            .get("ext_ids", [])
        )
        if not bl_part_ids or not bl_color_ids:
            return None
        return bl_part_ids[0], int(bl_color_ids[0]), part_name
    except Exception as e:
        log.warning("Rebrickable element mapping failed for element %s: %s", element_id, e)
        return None


async def lookup_element_mapping(element_id: int) -> tuple[str, int, str | None] | None:
    """Return (bl_part_no, bl_color_id, part_name) for a LEGO element_id via Rebrickable."""
    return await asyncio.to_thread(_fetch_element_mapping_sync, element_id)
