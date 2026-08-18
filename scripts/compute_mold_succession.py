#!/usr/bin/env python3
"""Computes the transitive closure of bricklink_alternates + BrickLink's own
similar_mold relationship groups into mold_succession_groups/_members --
real connected components ("families"), not just direct pairs.

Confirmed live 2026-08-17: bricklink_alternates is not transitively closed.
A direct lookup on part 15712 (BrickLink "Open O Clip", the current mold)
returns {44842, 2555, 93794} and silently misses 12825, which is only an
alternate of 2555, two hops away. This script closes that gap once so a
family lookup is a single group_id join instead of a live BFS.

Edges come from two sources, both treated as undirected:
  - every (part_no, alternate_no) row in bricklink_alternates
  - every pair of members sharing a group_id in
    brickstore_mold_relationship_members, restricted to
    relationship_type = 'similar_mold' (the "directly interchangeable"
    tier -- 'different_mold' groups are a different, weaker relationship
    and stay excluded, same distinction ingest_brickstore_catalog.py
    already draws for bricklink_alternates itself)

is_current is the group member with the highest non-null last_used_year;
if no member has one, the whole group is left with is_current=false on
every row (ambiguous family, nothing to flag -- acceptable for now: some
predecessor mold numbers, e.g. 44842, have zero independent BrickLink
catalog presence at all and no bl_part_catalog row, so their year data is
just NULL. No live-lookup/confidence-scoring for those is being built in
this pass).

Pure local graph computation over already-ingested tables -- no API calls,
no pacing, safe to re-run. Full truncate + reinsert each run (derived,
fully-recomputable data, same reasoning ingest_brickstore_catalog.py's
ingest_part_colors() uses for brickstore_part_colors).

Usage:
    DATABASE_URL=... python scripts/compute_mold_succession.py [--dry-run]
"""
import argparse
import os
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "postgresql://mocsource:changeme@localhost/mocsource")
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def load_edges(cur) -> list[tuple[str, str]]:
    edges = []

    cur.execute("SELECT part_no, alternate_no FROM bricklink_alternates")
    edges.extend(cur.fetchall())

    cur.execute(
        """
        SELECT group_id, part_no FROM brickstore_mold_relationship_members m
        JOIN brickstore_mold_relationship_groups g ON g.id = m.group_id
        WHERE g.relationship_type = 'similar_mold'
        ORDER BY group_id
        """
    )
    by_group: dict[int, list[str]] = {}
    for group_id, part_no in cur.fetchall():
        by_group.setdefault(group_id, []).append(part_no)
    for members in by_group.values():
        for i in range(1, len(members)):
            edges.append((members[0], members[i]))

    return edges


def pick_current(members: set[str], years: dict[str, tuple[int | None, int | None]]) -> str | None:
    """Highest non-null last_used_year wins; ties broken by lowest part_no
    string (deterministic, not claimed to be semantically meaningful --
    real ties, e.g. two parallel-production variants, are rare)."""
    best_year = max((years.get(p, (None, None))[0] for p in members), default=None,
                     key=lambda y: (y is not None, y))
    if best_year is None:
        return None
    candidates = sorted(p for p in members if years.get(p, (None, None))[0] == best_year)
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                         help="print computed groups without touching the database")
    args = parser.parse_args()

    start_time = time.monotonic()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    edges = load_edges(cur)
    print(f"{len(edges)} edge(s) loaded")

    uf = UnionFind()
    for a, b in edges:
        uf.union(a, b)

    components: dict[str, set[str]] = {}
    for node in uf.parent:
        components.setdefault(uf.find(node), set()).add(node)
    groups = [members for members in components.values() if len(members) > 1]
    print(f"{len(groups)} group(s) with 2+ members (of {len(components)} total connected components)")

    all_part_nos = {p for members in groups for p in members}
    cur.execute(
        "SELECT part_no, last_used_year, year_released FROM bl_part_catalog WHERE part_no = ANY(%s)",
        (list(all_part_nos),),
    )
    years = {part_no: (last_used_year, year_released) for part_no, last_used_year, year_released in cur.fetchall()}

    if args.dry_run:
        size_counts: dict[int, int] = {}
        for members in groups:
            size_counts[len(members)] = size_counts.get(len(members), 0) + 1
        print("Group size distribution:", dict(sorted(size_counts.items())))

        for members in groups:
            if "15712" in members:
                current_part = pick_current(members, years)
                print(f"\nSample group containing 15712 ({len(members)} members):")
                for p in sorted(members):
                    last_used_year, year_released = years.get(p, (None, None))
                    print(f"  {p:10s} last_used_year={last_used_year} year_released={year_released} "
                          f"is_current={p == current_part}")
                break

        duration_s = time.monotonic() - start_time
        total_members = sum(len(m) for m in groups)
        print(f"\n[dry-run] would write {len(groups)} groups, {total_members} members. "
              f"Done in {duration_s:.1f}s")
        return

    now = datetime.now(timezone.utc)
    cur.execute("TRUNCATE TABLE mold_succession_members")
    cur.execute("TRUNCATE TABLE mold_succession_groups RESTART IDENTITY CASCADE")

    for members in groups:
        cur.execute(
            "INSERT INTO mold_succession_groups (computed_at) VALUES (%s) RETURNING id",
            (now,),
        )
        group_id = cur.fetchone()[0]

        current_part = pick_current(members, years)
        rows = [
            (group_id, p, years.get(p, (None, None))[0], years.get(p, (None, None))[1], p == current_part)
            for p in sorted(members)
        ]
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO mold_succession_members (group_id, part_no, last_used_year, year_released, is_current) VALUES %s",
            rows,
        )

    conn.commit()
    cur.close()
    conn.close()

    duration_s = time.monotonic() - start_time
    print(f"\nDone in {duration_s:.1f}s. Groups: {len(groups)}, members: {sum(len(m) for m in groups)}")


if __name__ == "__main__":
    main()
