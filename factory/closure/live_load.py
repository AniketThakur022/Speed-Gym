#!/usr/bin/env python3
"""MERGE-window loader — derived REQUIRES edges + live Strategy-A closure.

Protocol (docs/rag/STRATEGY_A_CLOSURE_DESIGN.md + sync_manifest convention):
  1. MERGE the 294 derived REQUIRES edges into live Neo4j (idempotent; the 11
     curated edges are among them and simply match).
  2. Run Strategy A live: apoc.path.spanningTree over REQUIRES>, maxLevel 5,
     batched start nodes -> rows into prerequisite_closure_test (shadow),
     logged as a dry_run in sync_manifest.
  3. Diff the shadow table against the offline ground truth
     (data/factory/prerequisite_closure_v1.jsonl, 2,711 rows / 170 skills).
  4. On an EXACT match: promote into prerequisite_closure, load
     problem_requirements (2,457 Q-matrix rows), mark production in
     sync_manifest. On ANY mismatch: stop and report — no promotion.

Connections come from env (VMSG_NEO4J_URI/USER/PASS, VMSG_PG_DSN) with the
documented docker-compose defaults.
"""

import json
import os
import time
from pathlib import Path

import neo4j
import psycopg

NEO4J_URI = os.environ.get("VMSG_NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (os.environ.get("VMSG_NEO4J_USER", "neo4j"),
              os.environ.get("VMSG_NEO4J_PASS", "vmsg-dev-password"))
PG_DSN = os.environ.get("VMSG_PG_DSN", "postgresql://vmsg:vmsg@localhost:5432/vmsg")

EDGES = Path("data/factory/skill_requires_edges_v1.jsonl")
GROUND_TRUTH = Path("data/factory/prerequisite_closure_v1.jsonl")
QMATRIX = Path("data/factory/problem_requirements_v1.jsonl")
SOURCE = "factory/closure/live_load.py"


def manifest(pg, target, status, rows, t0, error=None):
    pg.execute(
        "INSERT INTO sync_manifest (source, target_table, status, rows_written, "
        "finished_at, duration_ms, error) VALUES (%s,%s,%s,%s,NOW(),%s,%s)",
        (SOURCE, target, status, rows, int((time.time() - t0) * 1000), error))


def main() -> int:
    edges = [json.loads(l) for l in EDGES.read_text().splitlines()]
    truth = {(r["descendant_skill"], r["ancestor_skill"]): r["min_depth"]
             for r in map(json.loads, GROUND_TRUTH.read_text().splitlines())}
    print(f"inputs: {len(edges)} edges, {len(truth)} ground-truth closure rows")

    driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as s, psycopg.connect(PG_DSN, autocommit=False) as pg_conn:
        pg = pg_conn.cursor()

        # -- 1. edge MERGE (idempotent) --
        t0 = time.time()
        rec = s.run("""
            UNWIND $edges AS e
            MATCH (a:Skill {name: e.from}), (b:Skill {name: e.to})
            MERGE (a)-[r:REQUIRES]->(b)
            ON CREATE SET r.created_by = 'skill_dag_builder_v1'
            SET r.source = e.source, r.support = e.support
            RETURN count(r) AS bound
            """, edges=edges).single()
        total = s.run("MATCH ()-[r:REQUIRES]->() RETURN count(r) AS n").single()["n"]
        missing = s.run("""
            UNWIND $edges AS e
            OPTIONAL MATCH (a:Skill {name: e.from}) OPTIONAL MATCH (b:Skill {name: e.to})
            WITH e, a, b WHERE a IS NULL OR b IS NULL RETURN e.from AS f, e.to AS t
            """, edges=edges).values()
        print(f"edge MERGE: bound {rec['bound']}, live REQUIRES total {total}, "
              f"unmatched endpoints {len(missing)}")
        if missing:
            print("  UNMATCHED:", missing[:10])
            return 1
        if total != len(edges):
            print(f"  WARNING: expected exactly {len(edges)} (file includes the 11 curated)")

        # -- 2. live Strategy-A closure -> shadow --
        t0 = time.time()
        pg.execute("TRUNCATE prerequisite_closure_test")
        # Start from every skill with outgoing REQUIRES — stubs included: a
        # stub-seeded skill (e.g. 'Division') is still a legitimate "what must I
        # know before X" query target. Matches offline ground-truth semantics.
        skills = [r["name"] for r in s.run(
            "MATCH (sk:Skill) WHERE (sk)-[:REQUIRES]->() "
            "RETURN sk.name AS name ORDER BY name")]
        rows = []
        for i in range(0, len(skills), 100):
            batch = skills[i:i + 100]
            for r in s.run("""
                UNWIND $names AS name
                MATCH (start:Skill {name: name})
                CALL apoc.path.spanningTree(start,
                     {relationshipFilter: 'REQUIRES>', minLevel: 1, maxLevel: 5, limit: 1000})
                YIELD path
                RETURN name AS descendant, last(nodes(path)).name AS ancestor,
                       length(path) AS depth
                """, names=batch):
                rows.append((r["descendant"], r["ancestor"], r["depth"]))
        with pg.copy("COPY prerequisite_closure_test (descendant_skill, ancestor_skill, "
                     "depth, min_depth, computed_at) FROM STDIN") as cp:
            for d, a, dep in rows:
                cp.write_row((d, a, dep, dep, time.strftime("%Y-%m-%d %H:%M:%S+00")))
        manifest(pg, "prerequisite_closure_test", "dry_run", len(rows), t0)
        pg_conn.commit()
        print(f"live closure (spanningTree): {len(rows)} rows over {len(skills)} skills "
              f"in {int((time.time()-t0)*1000)}ms")

        # -- 3. diff vs offline ground truth --
        live = {(d, a): dep for d, a, dep in rows}
        only_live = set(live) - set(truth)
        only_truth = set(truth) - set(live)
        depth_diff = [(k, truth[k], live[k]) for k in set(live) & set(truth)
                      if live[k] != truth[k]]
        print(f"diff: only_live={len(only_live)} only_truth={len(only_truth)} "
              f"depth_mismatch={len(depth_diff)}")
        if only_live or only_truth or depth_diff:
            for label, sample in (("only_live", list(only_live)[:5]),
                                  ("only_truth", list(only_truth)[:5]),
                                  ("depth", depth_diff[:5])):
                if sample:
                    print(f"  {label}: {sample}")
            manifest(pg, "prerequisite_closure", "failed", 0, t0,
                     error=f"shadow diff mismatch: +{len(only_live)}/-{len(only_truth)}"
                           f"/depth{len(depth_diff)}")
            pg_conn.commit()
            return 2

        # -- 4. promote + Q-matrix --
        t0 = time.time()
        pg.execute("TRUNCATE prerequisite_closure")
        pg.execute("INSERT INTO prerequisite_closure SELECT * FROM prerequisite_closure_test")
        manifest(pg, "prerequisite_closure", "production", len(rows), t0)
        t0 = time.time()
        qrows = [json.loads(l) for l in QMATRIX.read_text().splitlines()]
        pg.execute("TRUNCATE problem_requirements")
        with pg.copy("COPY problem_requirements (skill_name, template_id) FROM STDIN") as cp:
            for q in qrows:
                cp.write_row((q["skill_name"], q["template_id"]))
        manifest(pg, "problem_requirements", "production", len(qrows), t0)
        pg_conn.commit()
        pg.execute("SELECT count(*) FROM prerequisite_closure")
        n1 = pg.fetchone()[0]
        pg.execute("SELECT count(*) FROM problem_requirements")
        n2 = pg.fetchone()[0]
        print(f"PROMOTED: prerequisite_closure={n1}, problem_requirements={n2}")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
