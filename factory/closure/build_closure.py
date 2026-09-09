#!/usr/bin/env python3
"""Prerequisite-closure precompute (offline Strategy A equivalent).

BFS over the derived REQUIRES DAG (skill_requires_edges_v1.jsonl), depth <= 5,
keeping MIN depth per (descendant, ancestor) — the same result the live
apoc.path.spanningTree run will produce (docs/rag/STRATEGY_A_CLOSURE_DESIGN.md §3),
computed now from the recovered export so backend can load a ready table.

Also exports the depth-1 Q-matrix (Skill-PREREQUISITE_OF->Problem) as
problem_requirements_v1.jsonl.

Outputs (data/factory/):
  prerequisite_closure_v1.jsonl   {descendant_skill, ancestor_skill, min_depth}
  problem_requirements_v1.jsonl   {skill_name, template_id}
  closure_report_v1.json          stats for the benchmark/sync manifest
"""

import argparse
import json
import statistics
from collections import defaultdict, deque
from pathlib import Path

MAX_DEPTH = 5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--edges", default="data/factory/skill_requires_edges_v1.jsonl")
    ap.add_argument("--exports", default="incoming/topic_browser_full_package/db_exports")
    ap.add_argument("--out-dir", default="data/factory")
    ap.add_argument("--vocabulary-merge",
                    default="data/migrations/skill_vocabulary_applied_2026-09-08.json",
                    help="applied skill-vocabulary migration; the exports predate it. "
                         "Pass '' to emit the raw export vocabulary.")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    adj = defaultdict(list)  # dependent -> prerequisites
    nodes = set()
    for line in Path(args.edges).read_text().splitlines():
        e = json.loads(line)
        adj[e["from"]].append(e["to"])
        nodes.update((e["from"], e["to"]))

    closure_rows = []
    ancestor_counts = []
    for start in sorted(nodes):
        depth = {start: 0}
        q = deque([start])
        while q:
            v = q.popleft()
            if depth[v] >= MAX_DEPTH:
                continue
            for w in adj.get(v, ()):
                if w not in depth:  # BFS => first visit is min depth
                    depth[w] = depth[v] + 1
                    q.append(w)
        anc = [(a, d) for a, d in depth.items() if d > 0]
        ancestor_counts.append(len(anc))
        for a, d in sorted(anc):
            closure_rows.append({"descendant_skill": start, "ancestor_skill": a, "min_depth": d})

    with (out_dir / "prerequisite_closure_v1.jsonl").open("w") as f:
        for row in closure_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # The Q-matrix is the BKT join spine, and the export it is read from PREDATES the
    # 2026-09-08 skill-vocabulary migration. Emitting start_key verbatim reintroduces
    # all 48 names that migration removed, and live_load then TRUNCATEs and reloads the
    # live table from this file — measured, that put 90 rows naming deleted skills onto
    # the join spine. Canonicalise here for the same reason skill_dag_builder does:
    # rows whose skill merged away are REMAPPED, rows naming a structural non-skill are
    # DROPPED (they were never a skill), and the drop is reported rather than silent.
    merges, structural = {}, set()
    if args.vocabulary_merge:
        mig = json.loads(Path(args.vocabulary_merge).read_text())
        merges = dict(mig.get("merges") or {})
        structural = {d["name"] if isinstance(d, dict) else d
                      for d in (mig.get("structural_deletes") or [])}
    qmatrix_rows, remapped, dropped = 0, 0, 0
    seen_pairs = set()
    with (out_dir / "problem_requirements_v1.jsonl").open("w") as f:
        for line in (Path(args.exports) / "relationships.jsonl").read_text().splitlines():
            r = json.loads(line)
            if r["rel_type"] != "PREREQUISITE_OF":
                continue
            skill = r["start_key"]
            if skill in structural:
                dropped += 1
                continue
            if skill in merges:
                skill = merges[skill]
                remapped += 1
            # a merge can collapse two rows onto one (skill, problem) pair
            pair = (skill, r["end_key"])
            if pair in seen_pairs:
                dropped += 1
                continue
            seen_pairs.add(pair)
            f.write(json.dumps({"skill_name": skill, "template_id": r["end_key"]},
                               ensure_ascii=False) + "\n")
            qmatrix_rows += 1
    print(f"Q-matrix: {qmatrix_rows} rows ({remapped} remapped by the vocabulary merge, "
          f"{dropped} dropped as structural or duplicate-after-merge)")

    depths = [row["min_depth"] for row in closure_rows]
    report = {
        "skills_in_dag": len(nodes),
        "closure_rows": len(closure_rows),
        "depth_distribution": {d: depths.count(d) for d in range(1, MAX_DEPTH + 1)},
        "ancestors_per_skill": {
            "mean": round(statistics.mean(ancestor_counts), 2),
            "median": statistics.median(ancestor_counts),
            "max": max(ancestor_counts),
            "zero": ancestor_counts.count(0),
        },
        "problem_requirements_rows": qmatrix_rows,
        "max_depth_cap": MAX_DEPTH,
        "note": "Offline equivalent of Strategy A; live run must reproduce these counts "
                "(shadow-table diff) before promotion — see sync_manifest protocol.",
    }
    # Merge, don't clobber. This report also carries sections written elsewhere
    # (decline_log, stub_share, retraction notes); a fresh write silently deleted
    # them on every rebuild.
    report_path = out_dir / "closure_report_v1.json"
    if report_path.exists():
        existing = json.loads(report_path.read_text())
        existing.update(report)
        report = existing
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
