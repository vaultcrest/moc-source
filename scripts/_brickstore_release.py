"""Downloads and caches BrickStore's public BrickLink catalog release.

BrickLink's own bulk catalog-download feature (catalogDownload.asp) requires
an authenticated, BrickLink-partner-registered session we don't have
(confirmed 2026-07-16 by reading the GPL-3.0 BrickStore desktop app's
source). BrickStore's maintainer already solved this: an automated pipeline
logs into BrickLink and publishes the raw downloaded bulk files as a public,
unauthenticated GitHub Release at github.com/rgriebl/brickstore-database,
refreshed regularly. This module downloads that release's `downloads.zip`
asset (the raw per-endpoint XML/CSV/HTML BrickLink returned, not
BrickStore's own proprietary binary database format) and exposes iterators
over its contents.

"Did the release change" is checked via the GitHub API's release metadata
(tag_name + the downloads.zip asset's updated_at), not an HTTP ETag on the
download itself -- the actual download URL redirects through a signed,
time-limited Azure blob URL that changes on every request, so a normal
conditional GET can't be used as the change signal here.
"""
import csv
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

GITHUB_API_RELEASE_URL = "https://api.github.com/repos/rgriebl/brickstore-database/releases/latest"
DOWNLOAD_URL = "https://github.com/rgriebl/brickstore-database/releases/latest/download/downloads.zip"

DEFAULT_DATA_DIR = Path(os.environ.get("BRICKSTORE_DATA_DIR", "/opt/mocsource/data/brickstore"))
MARKER_FILENAME = ".release_marker.json"


def _marker_path(data_dir: Path) -> Path:
    return data_dir / MARKER_FILENAME


def _fetch_release_metadata() -> dict | None:
    try:
        resp = requests.get(GITHUB_API_RELEASE_URL, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  Failed to fetch brickstore-database release metadata: {e}", file=sys.stderr)
        return None
    data = resp.json()
    asset = next((a for a in data.get("assets", []) if a["name"] == "downloads.zip"), None)
    if not asset:
        print("  No downloads.zip asset found on latest brickstore-database release", file=sys.stderr)
        return None
    return {
        "tag_name": data["tag_name"],
        "asset_updated_at": asset["updated_at"],
        "download_url": asset["browser_download_url"],
        "size": asset["size"],
    }


def ensure_latest(data_dir: Path = DEFAULT_DATA_DIR, force: bool = False) -> Path | None:
    """Downloads + extracts the latest release if it's new, returns the extracted
    dir if new data was fetched this call, or None if already up to date."""
    meta = _fetch_release_metadata()
    if meta is None:
        return None

    marker = _marker_path(data_dir)
    if not force and marker.exists():
        prev = json.loads(marker.read_text())
        if prev.get("tag_name") == meta["tag_name"] and prev.get("asset_updated_at") == meta["asset_updated_at"]:
            print(f"  brickstore-database release unchanged ({meta['tag_name']}), skipping download")
            return None

    print(f"  Downloading brickstore-database {meta['tag_name']} ({meta['size']:,} bytes)...")
    resp = requests.get(meta["download_url"], timeout=300, stream=True)
    resp.raise_for_status()
    buf = io.BytesIO()
    for chunk in resp.iter_content(chunk_size=1024 * 1024):
        buf.write(chunk)
    buf.seek(0)

    extract_dir = data_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting to {extract_dir}...")
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(extract_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({**meta, "fetched_at": time.time()}))
    print("  Done.")
    return extract_dir


def iter_part_rows(extract_dir: Path):
    """Yields dicts from items/P.xml: part_no, category_id, name, alternate_item_ids (raw comma-separated)."""
    path = extract_dir / "items" / "P.xml"
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "ITEM":
            continue
        item_type = elem.findtext("ITEMTYPE")
        if item_type == "P":
            yield {
                "part_no": elem.findtext("ITEMID"),
                "category_id": elem.findtext("CATEGORY") or None,
                "name": elem.findtext("ITEMNAME"),
                "alternate_item_ids": elem.findtext("ALTITEMIDS") or None,
            }
        elem.clear()


def iter_minifig_rows(extract_dir: Path):
    """Yields dicts from items/M.csv: minifig_no, category_id, name."""
    path = extract_dir / "items" / "M.csv"
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            number = (row.get("Number") or "").strip()
            if not number:
                continue
            yield {
                "minifig_no": number,
                "category_id": (row.get("Category ID") or "").strip() or None,
                "name": (row.get("Name") or "").strip(),
            }


def _parse_inventory_xml(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    items = []
    for elem in root.findall("ITEM"):
        items.append({
            "item_type": elem.findtext("ITEMTYPE"),
            "part_no": elem.findtext("ITEMID"),
            "qty": int(elem.findtext("QTY") or 0),
            "color_id": (elem.findtext("COLOR") or None),
            "is_extra": (elem.findtext("EXTRA") or "N") == "Y",
            "is_alternate": (elem.findtext("ALTERNATE") or "N") == "Y",
            "match_id": int(elem.findtext("MATCHID") or 0),
            "is_counterpart": (elem.findtext("COUNTERPART") or "N") == "Y",
        })
    return items


def iter_minifig_inventory_files(extract_dir: Path):
    """Yields (minifig_no, [item dicts]) for every M/<id>.xml file."""
    m_dir = extract_dir / "M"
    if not m_dir.is_dir():
        return
    for path in m_dir.glob("*.xml"):
        yield path.stem, _parse_inventory_xml(path)


def iter_assembly_inventory_files(extract_dir: Path):
    """Yields (part_no, [item dicts]) for every P/<id>.xml file (parts that are
    themselves assemblies of other parts, e.g. a bicycle = frame + 2 tires)."""
    p_dir = extract_dir / "P"
    if not p_dir.is_dir():
        return
    for path in p_dir.glob("*.xml"):
        yield path.stem, _parse_inventory_xml(path)


def _color_name_to_id(extract_dir: Path) -> dict[str, int]:
    path = extract_dir / "colors.xml"
    mapping = {}
    for item in ET.parse(path).getroot().findall("ITEM"):
        name = item.findtext("COLORNAME")
        color_id = item.findtext("COLOR")
        if name and color_id is not None:
            mapping[name] = int(color_id)
    return mapping


def iter_color_year_rows(extract_dir: Path):
    """Yields (bl_id, year_from, year_to) from colors.xml's own
    COLORYEARFROM/COLORYEARTO fields -- BrickLink's own year-introduced data,
    distinct from (and found 2026-07-26 to disagree with, for a third of all
    colors) Rebrickable's colors.csv-derived rebrickable_year_from/_to."""
    path = extract_dir / "colors.xml"
    for item in ET.parse(path).getroot().findall("ITEM"):
        bl_id = item.findtext("COLOR")
        year_from = item.findtext("COLORYEARFROM")
        year_to = item.findtext("COLORYEARTO")
        if bl_id is None:
            continue
        yield int(bl_id), int(year_from) if year_from else None, int(year_to) if year_to else None


def iter_part_color_rows(extract_dir: Path):
    """Yields (part_no, color_id) pairs from part_color_codes.xml, joined
    against colors.xml's COLORNAME -> COLOR (numeric id). Skips any color
    name with no match in colors.xml (none observed as of 2026-07-16)."""
    name_to_id = _color_name_to_id(extract_dir)
    path = extract_dir / "part_color_codes.xml"
    seen = set()
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "ITEM":
            continue
        if elem.findtext("ITEMTYPE") == "P":
            part_no = elem.findtext("ITEMID")
            color_id = name_to_id.get(elem.findtext("COLOR"))
            if part_no and color_id is not None and (part_no, color_id) not in seen:
                seen.add((part_no, color_id))
                yield part_no, color_id
        elem.clear()


def open_mold_relationship_html(extract_dir: Path, filename: str) -> str:
    """filename e.g. 'similar_parts_with_similar_molds_1.html'."""
    path = extract_dir / "relationships" / filename
    return path.read_text(encoding="utf-8")
