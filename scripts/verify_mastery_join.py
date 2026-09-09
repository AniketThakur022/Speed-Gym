#!/usr/bin/env python3
"""Snapshot and diff the BKT mastery join surface.

The mastery key joins a learner's entire history, so a graph change that moves
one silently splits that learner's mastery across two keys. Counting nodes and
edges cannot see that — only resolving the key for every problem can.

This resolves keys the SAME way `services/api/app/routers/session.py` does:
the pin (`:Problem.mastery_key`) is authoritative, and the fallback is the
sorted pick over skill parents with structural names demoted. Keep the query
below in step with that router; if they drift, this stops being a guard.

    scripts/verify_mastery_join.py --snapshot before.json
    # ... graph change runs ...
    scripts/verify_mastery_join.py --compare before.json

Exit status is non-zero when any existing problem's key MOVED or a pin was
lost. New problems and newly-resolvable problems are reported but are not
failures — additive change is allowed, silent re-keying is not.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Verbatim from session.py: whole-string structural names only.
STRUCTURAL = (
    r"(?i)^\s*(chapter|ch\.?|section|sec\.?|unit|part|exercise|ex\.?|lesson)\s*[0-9ivxl.]*\s*$|^\s*[0-9.]+\s*$"
)

QUERY = """
MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
WHERE p.template_id IS NOT NULL
WITH p, s
  ORDER BY (CASE WHEN s.name =~ $structural_skill THEN 1 ELSE 0 END), s.name
WITH p, coalesce(p.mastery_key, head(collect(s.name))) AS skill,
     p.mastery_key AS pin, count(s) AS parents
RETURN p.template_id AS template_id, skill, pin, parents
ORDER BY template_id
"""

COUNTS = {
    "skills": "MATCH (n:Skill) RETURN count(n) AS c",
    "requires": "MATCH ()-[r:REQUIRES]->() RETURN count(r) AS c",
    "prerequisite_of": "MATCH ()-[r:PREREQUISITE_OF]->() RETURN count(r) AS c",
    "problems": "MATCH (n:Problem) RETURN count(n) AS c",
}


def collect() -> dict:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")),
    )
    try:
        with driver.session() as session:
            rows = session.run(QUERY, structural_skill=STRUCTURAL).data()
            counts = {k: session.run(q).single()["c"] for k, q in COUNTS.items()}
    finally:
        driver.close()
    return {
        "counts": counts,
        "resolved": {r["template_id"]: r["skill"] for r in rows},
        "pinned": {r["template_id"]: r["pin"] for r in rows if r["pin"] is not None},
    }


def report(snap: dict) -> None:
    c = snap["counts"]
    print(f"  skills={c['skills']} requires={c['requires']} "
          f"prerequisite_of={c['prerequisite_of']} problems={c['problems']}")
    print(f"  resolvable problems={len(snap['resolved'])} pinned={len(snap['pinned'])} "
          f"distinct keys={len(set(snap['resolved'].values()))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", metavar="FILE", help="write the current surface to FILE")
    ap.add_argument("--compare", metavar="FILE", help="diff the current surface against FILE")
    args = ap.parse_args()
    if not args.snapshot and not args.compare:
        ap.error("give --snapshot or --compare")

    now = collect()
    print("live mastery join surface:")
    report(now)

    if args.snapshot:
        with open(args.snapshot, "w") as fh:
            json.dump(now, fh, indent=2, sort_keys=True)
        print(f"  -> wrote {args.snapshot}")
        return 0

    with open(args.compare) as fh:
        before = json.load(fh)
    print(f"\nsnapshot {args.compare}:")
    report(before)

    moved = {
        t: (k, now["resolved"][t])
        for t, k in before["resolved"].items()
        if t in now["resolved"] and now["resolved"][t] != k
    }
    vanished = sorted(set(before["resolved"]) - set(now["resolved"]))
    unpinned = sorted(t for t in before["pinned"] if t not in now["pinned"])
    added = sorted(set(now["resolved"]) - set(before["resolved"]))

    print("\ndiff:")
    print(f"  keys MOVED:            {len(moved)}")
    print(f"  problems VANISHED:     {len(vanished)}")
    print(f"  pins LOST:             {len(unpinned)}")
    print(f"  problems newly joined: {len(added)}")
    for t, (was, is_) in sorted(moved.items())[:20]:
        print(f"    MOVED {t}: {was!r} -> {is_!r}")
    for t in vanished[:20]:
        print(f"    VANISHED {t}")
    for t in unpinned[:20]:
        print(f"    PIN LOST {t}")

    delta = {k: now["counts"][k] - before["counts"][k] for k in now["counts"]}
    print(f"  count delta: {delta}")

    failed = bool(moved or vanished or unpinned)
    print("\n" + ("FAIL: the mastery join surface changed for existing problems"
                  if failed else "OK: no existing problem's mastery key moved"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
