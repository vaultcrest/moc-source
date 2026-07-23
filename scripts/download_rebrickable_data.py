#!/usr/bin/env python3
"""Downloads Rebrickable's bulk parts.csv/elements.csv/colors.csv/
inventories.csv/inventory_parts.csv/minifigs.csv/inventory_minifigs.csv to
a local directory, refreshing the static snapshot import_rebrickable.py,
backfill_last_used_year.py, import_rebrickable_set_inventories.py, and
map_rebrickable_minifigs.py read from.

Root cause this replaces (found 2026-07-21): those two files previously
lived as two independently hand-maintained copies
(brick_palettes_generator/data/rebrickable/ for import_rebrickable.py,
moc-source-infra/data/elements.csv for backfill_last_used_year.py), both
last refreshed by hand in late June, both drifting further from
Rebrickable's actual current catalog every day since. Rebrickable keeps
adding BrickLink translations to its own data over time (confirmed live the
same day: several parts had translations that plainly didn't exist a week
earlier), so a stale snapshot means missing translations Rebrickable has
already resolved on their end -- not something any amount of clever
resolution logic downstream can fix, only a fresher snapshot can.

Same CDN download product already used for colors.csv in
scripts/backfill_rebrickable_colors.py
(https://cdn.rebrickable.com/media/downloads/colors.csv.gz, confirmed live,
unauthenticated) -- parts.csv.gz and elements.csv.gz live at the same base
URL (confirmed live 2026-07-21, both return 200). Unlike colors.csv (~275
rows, fetched fresh in-memory every run), parts.csv (~5.7MB) and
elements.csv (~2.8MB uncompressed) are large enough to persist to disk
rather than re-fetch into memory on every read -- this script's whole job
is refreshing that persisted copy, following ingest_brickstore_catalog.py's
BrickStore release cache convention (DEFAULT_DATA_DIR env override, same
style as scripts/_brickstore_release.py).

inventories.csv/inventory_parts.csv added 2026-07-22 for
import_rebrickable_set_inventories.py -- same CDN base, confirmed live
that both download fine (inventory_parts.csv is the big one, ~1.5M rows
across every set/version combined).

minifigs.csv/inventory_minifigs.csv added 2026-07-23 for
map_rebrickable_minifigs.py / import_rebrickable_minifig_inventories.py --
same CDN base. minifigs.csv (~17K rows, fig_num/name/num_parts) supplies
the names used for token-overlap disambiguation when a set has more than
one minifig; inventory_minifigs.csv (~23K rows, inventory_id/fig_num/qty)
supplies which fig_nums are in which set, the anchor used to bridge
Rebrickable's fig_num numbering to BrickLink's unrelated minifig_no
numbering (see map_rebrickable_minifigs.py's docstring for why no direct
mapping exists).

No DB writes, no API key needed (unauthenticated CDN downloads). Run
scripts/import_rebrickable.py / import_rebrickable_set_inventories.py
afterward to actually load the fresh data.

Usage:
    python scripts/download_rebrickable_data.py [--data-dir PATH]
"""
import argparse
import gzip
import os
import sys
from pathlib import Path

import requests

CDN_BASE = "https://cdn.rebrickable.com/media/downloads"
FILES = ["parts.csv", "elements.csv", "colors.csv", "inventories.csv", "inventory_parts.csv",
         "minifigs.csv", "inventory_minifigs.csv"]

DEFAULT_DATA_DIR = Path(os.environ.get("REBRICKABLE_DATA_DIR", "/opt/mocsource/data/rebrickable"))


def download_file(name: str, data_dir: Path) -> int:
    """Download and decompress {name}.csv.gz into data_dir/{name}. Returns
    the row count (excluding header), or -1 on failure."""
    url = f"{CDN_BASE}/{name}.gz"
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {name}.gz fetch failed: {e}", file=sys.stderr)
        return -1
    raw = gzip.decompress(resp.content)
    dest = data_dir / name
    dest.write_bytes(raw)
    row_count = raw.decode("utf-8", errors="replace").count("\n") - 1  # minus header
    return max(row_count, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                         help=f"directory to write {', '.join(FILES)} into (default {DEFAULT_DATA_DIR})")
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)

    failed = []
    for name in FILES:
        print(f"Downloading {name}.gz...")
        count = download_file(name, args.data_dir)
        if count < 0:
            failed.append(name)
        else:
            print(f"  {count} row(s) -> {args.data_dir / name}")

    if failed:
        print(f"\nFAILED: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    print(f"\nDone. Fresh Rebrickable data in {args.data_dir}")


if __name__ == "__main__":
    main()
