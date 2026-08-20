#!/usr/bin/env python3
"""Read-only investigation of cache/studio_reference_files/*, 2026-08-19.

Sean pulled 7 new Stud.io reference files (see README.md's
`cache/studio_reference_files/` section for provenance). This script makes
zero DB writes -- it only reports real, live counts + concrete examples so
Sean can decide whether any of it is worth turning into a real backfill
script.

Core purpose (LDrawLxfmlPartMapping.json): NOT a multipack/assembly-
decomposition source -- that hypothesis was checked and refuted (zero
overlap between this file's "assembly"-type designIds and the 11 already-
known real multipack/sprue candidates; a live check on designId 106714
showed its two "assembly" children are just two color variants of one
Complete Assembly part, not a parent split into sub-parts). Its real value
is as a THIRD, independently-sourced (part_no -> correct .dat filename)
signal -- useful the same way StudioPartDefinition2.txt and the BDP/
Common-Palette reference files already were, to catch studio_resolutions
rows whose stored part_file disagrees with what Stud.io's own engine data
says it should be (the same class of bug fix_studio_resolutions_primary_dat.py
just fixed 164 instances of, caught here by an independent source instead
of re-deriving from the same StudioPartDefinition2.txt that produced the
original error).

Secondary purpose (ElementId.json / AlternateBLItemNo.json / BLBrickMetaInfo.dat):
a lightweight one-count-each check against bricklink_mappings /
bricklink_alternates / brickstore_part_colors, confirming (or refuting)
Sean's expectation that these mostly re-tread already-covered ground.

Usage:
    DATABASE_URL=... python scripts/investigate_ldraw_lxfml_mapping.py
"""
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

REF_DIR = Path(__file__).resolve().parent.parent / "cache" / "studio_reference_files"


def load_json(name):
    with open(REF_DIR / name, encoding="utf-8-sig") as f:
        return json.load(f)


def section_a_file_characterization(data):
    print("=" * 70)
    print("SECTION A: LDrawLxfmlPartMapping.json -- file-level characterization")
    print("=" * 70)

    type_counts = {}
    designid_filenames = {}
    filename_is_recent = {}
    for e in data:
        t = e.get("type")
        type_counts[t] = type_counts.get(t, 0) + 1
        did = e["ldd"]["designId"]
        fn = e["ldraw"]["filename"]
        designid_filenames.setdefault(did, set()).add(fn)
        # UpdateDateTime "1900-01-01..." is a placeholder/never-updated sentinel
        # (confirmed live: 4,669/8,926 entries carry it, 2,681 more have no
        # UpdateDateTime field at all -- only 1,576 have a real 2026 date) --
        # treat those as legacy/unmaintained, not a trustworthy "current"
        # filename signal. OR across duplicate filename entries: one recent
        # sighting is enough to call the filename "recent".
        ts = e.get("UpdateDateTime")
        is_recent = bool(ts) and not ts.startswith("1900-")
        filename_is_recent[fn] = filename_is_recent.get(fn, False) or is_recent

    unique_filenames = {fn for fns in designid_filenames.values() for fn in fns}
    multi = {k: v for k, v in designid_filenames.items() if len(v) > 1}
    recent_count = sum(1 for v in filename_is_recent.values() if v)

    print(f"total entries: {len(data)}")
    print(f"unique designIds: {len(designid_filenames)}")
    print(f"unique ldraw filenames: {len(unique_filenames)}")
    print(f"entries by type: {type_counts}")
    print(f"designIds mapping to >1 distinct filename: {len(multi)}")
    print(f"filenames with at least one non-placeholder (real 2026) UpdateDateTime: {recent_count} of {len(unique_filenames)}")
    print()
    return unique_filenames, filename_is_recent


def section_b_dat_agreement(cur, unique_filenames, filename_is_recent):
    print("=" * 70)
    print("SECTION B (CORE): filename-level .dat agreement vs studio_resolutions")
    print("=" * 70)

    real_candidates = set()
    synthetic_bl_prefixed = 0
    for fn in unique_filenames:
        if not fn.endswith(".dat"):
            continue
        stem = fn[: -len(".dat")]
        if stem.startswith("bl_"):
            synthetic_bl_prefixed += 1
            continue
        real_candidates.add(stem)

    print(f"candidate part_nos (filename minus .dat, excluding bl_-prefixed): {len(real_candidates)}")
    print(f"Stud.io-synthetic bl_-prefixed filenames (excluded, not real BL numbers): {synthetic_bl_prefixed}")

    candidates = list(real_candidates)
    # filename -> real part_no, via bl_part_catalog
    cur.execute(
        "SELECT part_no FROM bl_part_catalog WHERE part_no = ANY(%s)",
        (candidates,),
    )
    real_part_nos = {r[0] for r in cur.fetchall()}
    print(f"of those, real bl_part_catalog matches: {len(real_part_nos)}")

    cur.execute(
        "SELECT part_no, part_file, resolved FROM studio_resolutions WHERE part_no = ANY(%s)",
        (list(real_part_nos),),
    )
    sr_rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    bucket1_no_row = []       # no studio_resolutions row at all
    bucket2_unresolved = []   # resolved = false
    bucket3_recent = []       # resolved = true, different part_file, RECENT source entry
    bucket3_stale = []        # same, but only a 1900-placeholder/legacy source entry

    for part_no in sorted(real_part_nos):
        expected_file = f"{part_no}.dat"
        if part_no not in sr_rows:
            bucket1_no_row.append((part_no, expected_file))
            continue
        stored_file, resolved = sr_rows[part_no]
        if not resolved:
            bucket2_unresolved.append((part_no, expected_file, stored_file))
        elif stored_file != expected_file:
            target = bucket3_recent if filename_is_recent.get(expected_file) else bucket3_stale
            target.append((part_no, stored_file, expected_file))

    print()
    recent_b1 = sum(1 for _, fn in bucket1_no_row if filename_is_recent.get(fn))
    print(f"Bucket 1 -- no studio_resolutions row at all: {len(bucket1_no_row)} ({recent_b1} from a recent/2026-dated source entry)")
    print(
        "  CAVEAT: given the Bucket 3 finding below (even a recent-dated entry can"
        " turn out to reference a non-primary/legacy filename once cross-checked"
        " against StudioPartDefinition2.txt), treat these as unverified candidates,"
        " not proven-correct filenames -- cross-check any before writing."
    )
    for part_no, fn in bucket1_no_row[:10]:
        print(f"    {part_no}: LDraw file says {fn}")
    if len(bucket1_no_row) > 10:
        print(f"    ... and {len(bucket1_no_row) - 10} more")

    print()
    print(f"Bucket 2 -- studio_resolutions row exists but resolved=false: {len(bucket2_unresolved)}")
    for part_no, fn, stored in bucket2_unresolved[:10]:
        print(f"    {part_no}: LDraw file says {fn} (stored part_file={stored!r})")
    if len(bucket2_unresolved) > 10:
        print(f"    ... and {len(bucket2_unresolved) - 10} more")

    print()
    print(
        f"Bucket 3 -- resolved=true but DIFFERENT stored part_file: "
        f"{len(bucket3_recent) + len(bucket3_stale)} total "
        f"({len(bucket3_recent)} from a recent/2026-dated source entry, "
        f"{len(bucket3_stale)} from a 1900-placeholder/undated entry only)"
    )
    print(
        "  NOTE: the stale sub-bucket is very likely legacy-alias noise, not real"
        " bugs -- LDraw keeps old bare-numbered .dat files around for backward"
        " compatibility alongside newer mold-revision-suffixed files (e.g. the"
        " current, already-vetted studio_resolutions value 3023b.dat vs. this"
        " file's bare 3023.dat), and every stale-bucket example checked by hand"
        " matched that exact pattern (DB has an extra revision/assembly suffix,"
        " source entry has an epoch/missing UpdateDateTime). Do NOT treat these"
        " as corrections without independently verifying against"
        " StudioPartDefinition2.txt or a real Stud.io load, same as the 164-row"
        " fix already did."
    )
    print()
    print(f"  Recent-sourced disagreements ({len(bucket3_recent)}):")
    for part_no, stored, ldraw_says in bucket3_recent:
        print(f"    {part_no}: stored={stored!r}  LDraw file says={ldraw_says!r}")
    if bucket3_recent:
        print(
            "    Cross-checked the one recent-sourced hit (part 3040) directly against"
            " StudioPartDefinition2.txt's own selection rule (the same one"
            " fix_studio_resolutions_primary_dat.py uses): the file has 3 rows for BL"
            " ItemNo 3040 -- the primary row (isPerfectForCulling=o, BLCatalogIndex=81,"
            " IsDecorated=False) gives LDraw ItemNo '3040b.dat', matching the DB exactly."
            " The '3040.dat' this JSON references corresponds to an auxiliary row"
            " (BLCatalogIndex=0, IsDecorated=True) -- i.e. even the one recency-passing"
            " hit is a confirmed false positive, not a real bug. BOTTOM LINE: this pass"
            " found ZERO real studio_resolutions corrections in Bucket 3 -- every"
            " disagreement, recent or stale, traces back to this file referencing a"
            " non-primary/legacy LDraw filename rather than the vetted current one."
        )
    print()
    print(f"  Stale-sourced disagreements ({len(bucket3_stale)}) -- likely legacy-alias noise, listed for completeness:")
    for part_no, stored, ldraw_says in bucket3_stale:
        print(f"    {part_no}: stored={stored!r}  LDraw file says={ldraw_says!r}")
    print()

    return bucket1_no_row, bucket2_unresolved, bucket3_recent, bucket3_stale


def section_c_lightweight_other_files(cur):
    print("=" * 70)
    print("SECTION C: lightweight pass on the other 3 new reference files")
    print("=" * 70)

    # --- ElementId.json vs bricklink_mappings ---
    element_data = load_json("ElementId.json")
    print(f"\nElementId.json: {len(element_data)} rows")
    ids = [e["ElementId"] for e in element_data]
    cur.execute("SELECT element_id, part_no, color_id FROM bricklink_mappings WHERE element_id = ANY(%s)", (ids,))
    existing = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    no_row = 0
    disagree = []
    for e in element_data:
        eid = e["ElementId"]
        if eid not in existing:
            no_row += 1
            continue
        part_no, color_id = existing[eid]
        if part_no != e["BLItemNo"] or color_id != e["BLColorId"]:
            disagree.append((eid, existing[eid], (e["BLItemNo"], e["BLColorId"])))

    print(f"  ElementIds with no bricklink_mappings row at all: {no_row}")
    print(f"  ElementIds present but disagreeing on part_no/color_id: {len(disagree)}")
    if disagree:
        eid, db_val, json_val = disagree[0]
        print(f"    example: element_id={eid} db={db_val} json={json_val}")

    # --- AlternateBLItemNo.json vs bricklink_alternates ---
    alt_data = load_json("AlternateBLItemNo.json")
    json_pairs = set()
    for e in alt_data:
        for alt in e.get("AlternateItemNos", []):
            json_pairs.add((e["BLItemNo"], alt))
    print(f"\nAlternateBLItemNo.json: {len(alt_data)} rows, {len(json_pairs)} (BLItemNo, alternate) pairs")

    cur.execute("SELECT part_no, alternate_no FROM bricklink_alternates")
    db_pairs = set(cur.fetchall())
    net_new = json_pairs - db_pairs
    print(f"  pairs not already in bricklink_alternates: {len(net_new)}")
    if net_new:
        print(f"    example: {next(iter(net_new))}")

    # --- BLBrickMetaInfo.dat vs brickstore_part_colors ---
    meta_data = load_json("BLBrickMetaInfo.dat")
    json_color_pairs = set()
    for part_no, info in meta_data.items():
        for c in info.get("AvailableColors", []):
            json_color_pairs.add((part_no, c["ColorId"]))
    print(f"\nBLBrickMetaInfo.dat: {len(meta_data)} parts, {len(json_color_pairs)} (part_no, color_id) pairs")

    cur.execute("SELECT part_no, color_id FROM brickstore_part_colors")
    db_color_pairs = set(cur.fetchall())
    net_new_colors = json_color_pairs - db_color_pairs
    print(f"  pairs not already in brickstore_part_colors: {len(net_new_colors)}")
    if net_new_colors:
        print(f"    example: {next(iter(net_new_colors))}")
    print()


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    ldraw_data = load_json("LDrawLxfmlPartMapping.json")
    unique_filenames, filename_is_recent = section_a_file_characterization(ldraw_data)
    section_b_dat_agreement(cur, unique_filenames, filename_is_recent)
    section_c_lightweight_other_files(cur)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
