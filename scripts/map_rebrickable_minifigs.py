#!/usr/bin/env python3
"""Builds fig_num <-> minifig_no mappings between Rebrickable's minifig
numbering and BrickLink's, so Rebrickable's minifig part-inventories can
eventually be joined against brickstore_minifig_catalog.

Found 2026-07-22/23: brickstore_minifig_catalog has 1,948 minifigs (10.2%)
with no part-inventory data anywhere (BrickStore's M/ bulk XML only covers
17,106/19,054). Rebrickable DOES carry minifig-level inventories -- 17,068
of them, keyed by fig_num (e.g. fig-017719) -- but unlike lego_sets, where
BrickLink and Rebrickable share the same set_num string, fig_num has no
relationship to BrickLink's minifig_no (e.g. hp637). Confirmed live that
neither Rebrickable's minifig API nor its parts API (which does carry
BrickLink external_ids for regular parts) exposes any BrickLink
cross-reference for minifigs, and that exact name matching only resolves
~10% of pairs, with some of those already ambiguous.

The bridge is set_num, which both catalogs DO share. For a given set:
  - Rebrickable's inventory_minifigs.csv says which fig_nums are inside
    (winning max-version inventory per set, same logic as
    import_rebrickable_set_inventories.py).
  - BrickLink's GET /items/SET/{no}/subsets (BLClient.fetch_subsets) says
    which minifig_nos are inside.
Confirmed live against set 76478-1: both sides agreed on a count of 2
minifigs, and name-token overlap unambiguously paired
hp314<->fig-011589 ("Harry Potter, Gryffindor Robes Open...") and
hp637<->fig-017719 ("Albus Dumbledore, Dark Red Robe...") even though
neither pair is an exact string match.

Resolution per set:
  - Exactly one minifig on both sides -> direct pair, no name comparison
    needed (method='single_minifig_set'). ~4,321 of the 9,329 minifig-
    bearing sets are this simple case.
  - More than one minifig on either side -> normalize names (lowercase,
    alnum tokens only), score every RB-fig x BL-minifig pair in the set by
    Jaccard token overlap, greedy-assign mutual-best pairs. A pairing is
    only accepted if it's the unambiguous best for BOTH sides involved and
    clears MIN_MARGIN over the runner-up -- ties/near-ties are left
    unresolved rather than guessed (method='name_overlap_disambiguated').
  - A resolved pair is only written if it doesn't conflict with an
    already-stored mapping for either fig_num or minifig_no (global 1:1);
    conflicts are logged and skipped, never overwritten.

Only the 9,329 sets Rebrickable says contain >=1 minifig are crawled (not
every set) -- sized and confirmed live 2026-07-22.

Resumable via minifig_mapping_scan_log (set_num-keyed) -- a set that
resolves zero pairs (ambiguous, or its minifigs already mapped via another
set) is still marked scanned, same rationale as bl_price_guide_scan_log.

Usage:
    DATABASE_URL=... BRICKLINK_...=... python scripts/map_rebrickable_minifigs.py [--data-dir PATH] [--dry-run]
    DATABASE_URL=... BRICKLINK_...=... python scripts/map_rebrickable_minifigs.py --set-num 76478-1 [--dry-run]
"""
import argparse
import csv
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from _bricklink_lookup import BLClient
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("REBRICKABLE_DATA_DIR", "/opt/mocsource/data/rebrickable"))

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

BRICKLINK_CONSUMER_KEY = os.environ.get("BRICKLINK_CONSUMER_KEY", "")
BRICKLINK_CONSUMER_SECRET = os.environ.get("BRICKLINK_CONSUMER_SECRET", "")
BRICKLINK_TOKEN = os.environ.get("BRICKLINK_TOKEN", "")
BRICKLINK_TOKEN_SECRET = os.environ.get("BRICKLINK_TOKEN_SECRET", "")

bl_client = BLClient(BRICKLINK_CONSUMER_KEY, BRICKLINK_CONSUMER_SECRET, BRICKLINK_TOKEN, BRICKLINK_TOKEN_SECRET)

INTER_CALL_DELAY = 1.0  # polite pacing, matches scrape_bl_price_guide.py's convention
MAX_CONSECUTIVE_FAILURES = 5
MIN_MARGIN = 0.15  # winning Jaccard score must beat the runner-up by at least this much

UPSERT_MAPPING_SQL = """
    INSERT INTO minifig_mappings (fig_num, minifig_no, method, matched_via_set_num, created_at)
    VALUES (%s, %s, %s, %s, %s)
"""

UPSERT_SCAN_LOG_SQL = """
    INSERT INTO minifig_mapping_scan_log (set_num, scanned_at)
    VALUES (%s, %s)
    ON CONFLICT (set_num) DO UPDATE SET scanned_at = EXCLUDED.scanned_at
"""


def load_rb_minifig_names(data_dir: Path) -> dict[str, str]:
    """{fig_num: name} from minifigs.csv, ~17K rows."""
    names = {}
    with open(data_dir / "minifigs.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names[row["fig_num"]] = row["name"]
    return names


def load_rb_set_minifigs(data_dir: Path) -> dict[str, dict[str, int]]:
    """{set_num: {fig_num: qty}} for every set with >=1 minifig, winning
    (max-version) inventory only -- mirrors
    import_rebrickable_set_inventories.py's winning-inventory logic."""
    best_version: dict[str, int] = {}
    best_inv_id: dict[str, int] = {}
    with open(data_dir / "inventories.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            set_num = row["set_num"]
            if set_num.startswith("fig-"):
                continue  # a minifig's own inventory of parts, not a set
            try:
                inv_id = int(row["id"])
                version = int(row["version"])
            except (ValueError, KeyError):
                continue
            if version > best_version.get(set_num, -1):
                best_version[set_num] = version
                best_inv_id[set_num] = inv_id
    inv_to_set = {inv_id: set_num for set_num, inv_id in best_inv_id.items()}
    winning_ids = set(inv_to_set)

    set_minifigs: dict[str, dict[str, int]] = defaultdict(dict)
    with open(data_dir / "inventory_minifigs.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                inv_id = int(row["inventory_id"])
                qty = int(row["quantity"])
            except (ValueError, KeyError):
                continue
            if inv_id not in winning_ids:
                continue
            set_num = inv_to_set[inv_id]
            fig_num = row["fig_num"]
            set_minifigs[set_num][fig_num] = set_minifigs[set_num].get(fig_num, 0) + qty
    return dict(set_minifigs)


def normalize(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (name or "").lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def resolve_set(
    rb_figs: dict[str, int], bl_minifigs: list[dict], rb_names: dict[str, str]
) -> tuple[list[tuple[str, str, str]], int]:
    """Returns (resolved_pairs, ambiguous_count) for one set.
    resolved_pairs: [(fig_num, minifig_no, method), ...]"""
    bl_by_no: dict[str, dict] = {}
    for entry in bl_minifigs:
        no = entry["no"]
        if no not in bl_by_no:
            bl_by_no[no] = {"name": entry["name"], "quantity": 0}
        bl_by_no[no]["quantity"] += entry.get("quantity", 0)

    fig_nums = list(rb_figs)
    minifig_nos = list(bl_by_no)

    if len(fig_nums) == 1 and len(minifig_nos) == 1:
        return [(fig_nums[0], minifig_nos[0], "single_minifig_set")], 0

    if not fig_nums or not minifig_nos:
        return [], 0

    # Score every RB-fig x BL-minifig pair, greedily accept mutual-best
    # pairs that clear MIN_MARGIN over their runner-up on both sides.
    scores = {
        (fn, mn): jaccard(normalize(rb_names.get(fn, "")), normalize(bl_by_no[mn]["name"]))
        for fn in fig_nums for mn in minifig_nos
    }
    resolved = []
    ambiguous = 0
    remaining_figs, remaining_minifigs = set(fig_nums), set(minifig_nos)
    candidates = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    for (fn, mn), score in candidates:
        if fn not in remaining_figs or mn not in remaining_minifigs or score <= 0:
            continue
        fig_scores = sorted((scores[(fn, m)] for m in remaining_minifigs), reverse=True)
        minifig_scores = sorted((scores[(f, mn)] for f in remaining_figs), reverse=True)
        is_best_for_fig = fig_scores[0] == score and (len(fig_scores) == 1 or fig_scores[0] - fig_scores[1] >= MIN_MARGIN)
        is_best_for_minifig = minifig_scores[0] == score and (len(minifig_scores) == 1 or minifig_scores[0] - minifig_scores[1] >= MIN_MARGIN)
        if is_best_for_fig and is_best_for_minifig:
            resolved.append((fn, mn, "name_overlap_disambiguated"))
            remaining_figs.discard(fn)
            remaining_minifigs.discard(mn)
    ambiguous = len(remaining_figs) + len(remaining_minifigs)
    return resolved, ambiguous


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                         help=f"directory containing inventories.csv/inventory_minifigs.csv/minifigs.csv (default {DEFAULT_DATA_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                         help="print resolution stats without touching the database")
    parser.add_argument("--set-num", nargs="+", default=None,
                         help="process exactly these set_nums, bypassing the minifig_mapping_scan_log gate")
    args = parser.parse_args()

    for fname in ("inventories.csv", "inventory_minifigs.csv", "minifigs.csv"):
        if not (args.data_dir / fname).exists():
            print(f"ERROR: {args.data_dir / fname} not found -- run download_rebrickable_data.py first", file=sys.stderr)
            sys.exit(1)

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    print("Scanning inventories.csv/inventory_minifigs.csv for per-set minifig lists...")
    set_minifigs = load_rb_set_minifigs(args.data_dir)
    print(f"  {len(set_minifigs)} set(s) have >=1 minifig per Rebrickable")
    rb_names = load_rb_minifig_names(args.data_dir)

    if args.set_num:
        pending = [s for s in args.set_num if s in set_minifigs]
        skipped_no_minifigs = [s for s in args.set_num if s not in set_minifigs]
        if skipped_no_minifigs:
            print(f"  (skipping {skipped_no_minifigs}: no Rebrickable minifig data)")
        print(f"Processing {len(pending)} explicitly-specified set_num(s)")
    else:
        cur.execute("SELECT set_num FROM minifig_mapping_scan_log")
        already_scanned = {r[0] for r in cur.fetchall()}
        pending = [s for s in set_minifigs if s not in already_scanned]
        print(f"{len(pending)} set(s) pending (of {len(set_minifigs)} total minifig-bearing sets)")

    if not pending:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    # Existing mappings, both directions, kept in memory to enforce global
    # 1:1 without a round-trip per candidate pair.
    cur.execute("SELECT fig_num, minifig_no FROM minifig_mappings")
    fig_to_minifig: dict[str, str] = {}
    minifig_to_fig: dict[str, str] = {}
    for fig_num, minifig_no in cur.fetchall():
        fig_to_minifig[fig_num] = minifig_no
        minifig_to_fig[minifig_no] = fig_num

    stats = {"processed": 0, "skipped_transient": 0, "resolved": 0, "ambiguous": 0, "conflicts": 0}
    method_counts: dict[str, int] = defaultdict(int)
    consecutive_failures = 0
    now = datetime.now(timezone.utc)

    for i, set_num in enumerate(pending):
        rb_figs = set_minifigs[set_num]
        attempted, bl_minifigs = bl_client.fetch_subsets(set_num)
        if not attempted:
            stats["skipped_transient"] += 1
            consecutive_failures += 1
            print(f"[{i + 1}/{len(pending)}] {set_num}: skipped (transient failure)", flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"{MAX_CONSECUTIVE_FAILURES} consecutive transient failures — aborting run early", file=sys.stderr)
                break
            if i < len(pending) - 1:
                time.sleep(INTER_CALL_DELAY)
            continue
        consecutive_failures = 0

        resolved, ambiguous = resolve_set(rb_figs, bl_minifigs or [], rb_names)
        written = 0
        for fig_num, minifig_no, method in resolved:
            existing_minifig = fig_to_minifig.get(fig_num)
            existing_fig = minifig_to_fig.get(minifig_no)
            if existing_minifig is not None and existing_minifig != minifig_no:
                stats["conflicts"] += 1
                print(f"    CONFLICT: {fig_num} already mapped to {existing_minifig}, "
                      f"set {set_num} proposes {minifig_no} -- skipping", file=sys.stderr)
                continue
            if existing_fig is not None and existing_fig != fig_num:
                stats["conflicts"] += 1
                print(f"    CONFLICT: {minifig_no} already mapped to {existing_fig}, "
                      f"set {set_num} proposes {fig_num} -- skipping", file=sys.stderr)
                continue
            if existing_minifig == minifig_no:
                continue  # already resolved via an earlier set, nothing new
            if args.dry_run:
                print(f"    [dry-run] {fig_num} <-> {minifig_no} ({method}, via {set_num})")
            else:
                cur.execute(UPSERT_MAPPING_SQL, (fig_num, minifig_no, method, set_num, now))
            fig_to_minifig[fig_num] = minifig_no
            minifig_to_fig[minifig_no] = fig_num
            method_counts[method] += 1
            written += 1

        if not args.dry_run:
            cur.execute(UPSERT_SCAN_LOG_SQL, (set_num, now))

        stats["processed"] += 1
        stats["resolved"] += written
        stats["ambiguous"] += ambiguous
        print(f"[{i + 1}/{len(pending)}] {set_num}: {written} pair(s) resolved, {ambiguous} left ambiguous", flush=True)

        if not args.dry_run and stats["processed"] % 200 == 0:
            conn.commit()
        if i < len(pending) - 1:
            time.sleep(INTER_CALL_DELAY)

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    mins, secs = divmod(int(duration_s), 60)
    print(f"\nDone in {mins}m {secs}s. Sets processed: {stats['processed']}, "
          f"skipped (transient) {stats['skipped_transient']}")
    print(f"  Pairs resolved  : {stats['resolved']} ({dict(method_counts)})")
    print(f"  Left ambiguous  : {stats['ambiguous']}")
    print(f"  Conflicts       : {stats['conflicts']}")


if __name__ == "__main__":
    main()
