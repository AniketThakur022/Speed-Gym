#!/usr/bin/env python3
"""Skill-DAG builder — derives the canonical Skill->Skill REQUIRES edge set.

Implements Step 0 of docs/rag/STRATEGY_A_CLOSURE_DESIGN.md against the recovered
db_exports (offline; MERGE into live Neo4j happens later via the emitted Cypher).

Edge direction: dependent -> prerequisite (matches the 11 curated live REQUIRES).
Sources, by precedence: curated (live REQUIRES) > next_topic (inverted NEXT_TOPIC)
> chain_derived (taught-skill S REQUIRES each resolved prerequisite_chain member,
set semantics, support >= MIN_SUPPORT, no chain-internal pairs, no self-loops,
no derived edges from root skills).

Outputs:
  data/factory/skill_requires_edges_v1.jsonl   {from, to, source, support}
  data/factory/skill_dag_report_v1.json        resolution/edge/cycle statistics
  factory/closure/load_requires_edges.cypher   idempotent MERGE loader for backend
"""

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

MIN_SUPPORT = 2


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold().strip()
    return re.sub(r"\s+", " ", s)


def load_registry_aliases(path: Path) -> dict[str, str]:
    """alias(normed) -> canonical, from ontology_registry.yaml (flat regex parse,
    stdlib-only; the file is simple 'canonical:'/'aliases:' YAML)."""
    alias_map = {}
    canonical = None
    for line in path.read_text().splitlines():
        m = re.match(r'\s*-\s*canonical:\s*"(.+)"', line)
        if m:
            canonical = m.group(1)
            alias_map[norm(canonical)] = canonical
            continue
        m = re.match(r'\s*aliases:\s*\[(.*)\]', line)
        if m and canonical:
            for a in re.findall(r'"([^"]+)"', m.group(1)):
                alias_map.setdefault(norm(a), canonical)
    return alias_map


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exports", default="incoming/topic_browser_full_package/db_exports")
    ap.add_argument("--templates", default="incoming/topic_browser_full_package/content_data/templates/solve_along")
    ap.add_argument("--registry", default="incoming/topic_browser_full_package/schemas_and_taxonomy/ontology_registry.yaml")
    ap.add_argument("--out-dir", default="data/factory")
    args = ap.parse_args()
    exports, out_dir = Path(args.exports), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- live skills ---
    skills, roots = {}, set()  # name -> node; root names
    norm_to_name = {}
    for line in (exports / "nodes.jsonl").read_text().splitlines():
        n = json.loads(line)
        if n["_label"] != "Skill":
            continue
        name = n["name"]
        skills[name] = n
        norm_to_name.setdefault(norm(name), name)
        if n.get("name_norm"):
            norm_to_name.setdefault(norm(n["name_norm"]), name)
        if n.get("is_root"):
            roots.add(name)

    alias_map = load_registry_aliases(Path(args.registry))

    def resolve(s: str | None) -> str | None:
        if not s:
            return None
        if s in skills:
            return s
        hit = norm_to_name.get(norm(s))
        if hit:
            return hit
        canon = alias_map.get(norm(s))
        if canon and canon in skills:
            return canon
        if canon and norm(canon) in norm_to_name:
            return norm_to_name[norm(canon)]
        return None

    # --- live edges ---
    curated, next_topic, teaches = [], [], {}
    for line in (exports / "relationships.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["rel_type"] == "REQUIRES":
            curated.append((r["start_key"], r["end_key"]))
        elif r["rel_type"] == "NEXT_TOPIC":
            next_topic.append((r["end_key"], r["start_key"]))  # inverted: later REQUIRES earlier
        elif r["rel_type"] == "TEACHES":
            teaches[r["start_key"]] = r["end_key"]

    # --- templates (dedup by id, prefer enriched copy) ---
    by_id: dict[str, dict] = {}
    for path in sorted(Path(args.templates).glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            tid = rec["template_id"]
            score = (1 if rec.get("_validation_status") else 0, len(rec))
            if tid not in by_id or score > (1 if by_id[tid].get("_validation_status") else 0, len(by_id[tid])):
                by_id[tid] = rec

    # --- derive chain edges ---
    support = Counter()
    s_resolution = Counter()
    unresolved_members = Counter()
    for tid, rec in by_id.items():
        c = rec.get("concept") or {}
        S = resolve(c.get("sub_topic"))
        how = "sub_topic"
        if S is None:
            S = resolve(teaches.get(tid))
            how = "teaches"
        if S is None:
            S = resolve(c.get("technique_name"))
            how = "technique_name"
        if S is None:
            s_resolution["unresolved"] += 1
            continue
        s_resolution[how] += 1
        for member in rec.get("prerequisite_chain") or []:
            M = resolve(member)
            if M is None:
                unresolved_members[member] += 1
                continue
            if M == S:
                continue
            support[(S, M)] += 1

    curated_set = set(curated)
    next_set = set(next_topic) - curated_set
    derived, dropped = [], Counter()
    for (s, m), n in sorted(support.items()):
        if n < MIN_SUPPORT:
            dropped["below_support"] += 1
            continue
        if (s, m) in curated_set or (s, m) in next_set:
            dropped["already_curated_or_next_topic"] += 1
            continue
        if s in roots:
            dropped["derived_from_root"] += 1
            continue
        derived.append((s, m, n))

    edges = ([(s, m, "curated", 1) for s, m in curated]
             + [(s, m, "next_topic", 1) for s, m in next_set]
             + [(s, m, "chain_derived", n) for s, m, n in derived])

    # --- cycle break: drop lowest-support derived edge per SCC, iterate ---
    removed_for_cycles = []
    while True:
        adj = defaultdict(list)
        for s, m, _src, _n in edges:
            adj[s].append(m)
        index, low, on_stack, stack, sccs = {}, {}, set(), [], []
        counter = [0]

        def strongconnect(v):  # iterative Tarjan
            work = [(v, 0)]
            while work:
                node, pi = work[-1]
                if pi == 0:
                    index[node] = low[node] = counter[0]
                    counter[0] += 1
                    stack.append(node)
                    on_stack.add(node)
                recurse = False
                for i in range(pi, len(adj[node])):
                    w = adj[node][i]
                    if w not in index:
                        work[-1] = (node, i + 1)
                        work.append((w, 0))
                        recurse = True
                        break
                    if w in on_stack:
                        low[node] = min(low[node], index[w])
                if recurse:
                    continue
                if low[node] == index[node]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    if len(comp) > 1:
                        sccs.append(set(comp))
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])

        for v in list(adj):
            if v not in index:
                strongconnect(v)
        if not sccs:
            break
        for comp in sccs:
            candidates = [(n, i) for i, (s, m, src, n) in enumerate(edges)
                          if src == "chain_derived" and s in comp and m in comp]
            if not candidates:  # cycle among curated/next_topic edges: report, do not auto-fix
                removed_for_cycles.append({"scc": sorted(comp), "action": "UNRESOLVED_curated_cycle"})
                sccs = []
                break
            _, idx = min(candidates)
            s, m, src, n = edges.pop(idx)
            removed_for_cycles.append({"removed": [s, m], "support": n, "scc_size": len(comp)})
        if sccs == []:
            break

    # --- outputs ---
    edges_path = out_dir / "skill_requires_edges_v1.jsonl"
    with edges_path.open("w") as f:
        for s, m, src, n in sorted(edges):
            f.write(json.dumps({"from": s, "to": m, "source": src, "support": n}, ensure_ascii=False) + "\n")

    out_deg = Counter(s for s, *_ in edges)
    report = {
        "edges_total": len(edges),
        "edges_by_source": dict(Counter(src for _s, _m, src, _n in edges)),
        "taught_skill_resolution": dict(s_resolution),
        "chain_pairs_raw": len(support),
        "dropped": dict(dropped),
        "cycle_removals": removed_for_cycles,
        "root_out_degrees": {r: out_deg.get(r, 0) for r in sorted(roots)},
        "skills_with_outgoing": len(out_deg),
        "skills_total": len(skills),
        "unresolved_chain_members_top20": unresolved_members.most_common(20),
        "unresolved_chain_member_mentions": sum(unresolved_members.values()),
    }
    (out_dir / "skill_dag_report_v1.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))

    cypher = """// Idempotent loader for derived Skill->Skill REQUIRES edges (RAG workstream).
// Run AFTER the graph is re-seeded from db_exports. Params: $edges = rows of
// {from, to, source, support} from data/factory/skill_requires_edges_v1.jsonl.
// Curated live edges are untouched (MERGE matches them); derived edges carry provenance.
UNWIND $edges AS e
MATCH (a:Skill {name: e.from}), (b:Skill {name: e.to})
MERGE (a)-[r:REQUIRES]->(b)
ON CREATE SET r.source = e.source, r.support = e.support, r.created_by = 'skill_dag_builder_v1'
SET r.support = e.support;
"""
    Path("factory/closure/load_requires_edges.cypher").write_text(cypher)

    print(f"edges: {len(edges)} {report['edges_by_source']}")
    print(f"taught-skill resolution: {dict(s_resolution)}")
    print(f"dropped: {dict(dropped)} | cycles fixed: {len(removed_for_cycles)}")
    print(f"unresolved member mentions: {report['unresolved_chain_member_mentions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
