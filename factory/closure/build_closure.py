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

    qmatrix_rows = 0
    with (out_dir / "problem_requirements_v1.jsonl").open("w") as f:
        for line in (Path(args.exports) / "relationships.jsonl").read_text().splitlines():
            r = json.loads(line)
            if r["rel_type"] == "PREREQUISITE_OF":
                f.write(json.dumps({"skill_name": r["start_key"], "template_id": r["end_key"]},
                                   ensure_ascii=False) + "\n")
                qmatrix_rows += 1

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
    (out_dir / "closure_report_v1.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
