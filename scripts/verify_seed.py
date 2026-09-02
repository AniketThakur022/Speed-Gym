#!/usr/bin/env python3
"""VMSG seed verification — file mode (no DBs needed) and db mode.

--files : verify the recovered db_exports against their manifest:
          sha256 of nodes/relationships files, per-label node counts,
          per-type relationship counts, chunk count + embedding dimension,
          problems/registry row counts.
--db    : compare live Postgres/Neo4j counts against the manifest.

Exit code 0 = everything matches; 1 = at least one mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORTS = ROOT / "incoming" / "topic_browser_full_package" / "db_exports"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")

FAILURES: list[str] = []


def check(name: str, actual, expected) -> None:
    ok = actual == expected
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {name}: {actual}" + ("" if ok else f" (expected {expected})"))
    if not ok:
        FAILURES.append(name)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_files(exports: Path) -> None:
    manifest = json.loads((exports / "manifest.json").read_text())

    print("File integrity (sha256 vs manifest):")
    for key, fname in (("nodes_jsonl", "nodes.jsonl"), ("relationships_jsonl", "relationships.jsonl")):
        check(fname + " sha256", sha256_file(exports / fname), manifest["files"][key]["sha256"])

    print("Node counts by label:")
    labels: Counter = Counter()
    with open(exports / "nodes.jsonl") as f:
        for line in f:
            labels[json.loads(line)["_label"]] += 1
    for label, expected in manifest["nodes_by_label"].items():
        check(f":{label}", labels.get(label, 0), expected)
    check("nodes total", sum(labels.values()), manifest["nodes_total"])

    print("Relationship counts by type:")
    rels: Counter = Counter()
    with open(exports / "relationships.jsonl") as f:
        for line in f:
            rels[json.loads(line)["rel_type"]] += 1
    for rtype, expected in manifest["relationships_by_type"].items():
        check(f"[:{rtype}]", rels.get(rtype, 0), expected)
    check("relationships total", sum(rels.values()), manifest["relationships_total"])

    print("Postgres-bound exports:")
    n_chunks, bad_dims, null_embs = 0, 0, 0
    with open(exports / "chunks.jsonl") as f:
        for line in f:
            r = json.loads(line)
            n_chunks += 1
            emb = r.get("embedding")
            if emb is None:
                null_embs += 1
                continue
            vals = json.loads(emb) if isinstance(emb, str) else emb
            if len(vals) != 1536:
                bad_dims += 1
    check("chunks.jsonl rows", n_chunks, 4943)
    check("embedding dim!=1536 violations", bad_dims, 0)
    check("null embeddings", null_embs, 0)

    for fname in ("problems.jsonl", "registry.jsonl"):
        with open(exports / fname) as f:
            count = sum(1 for l in f if l.strip())
        print(f"  [--- ] {fname}: {count} rows (no manifest expectation; recorded)")


def verify_db(exports: Path) -> None:
    manifest = json.loads((exports / "manifest.json").read_text())

    import psycopg

    print("Postgres counts:")
    with psycopg.connect(DATABASE_URL) as conn:
        for table, expected in (("chunks", 4943), ("ontology_registry", None), ("problems", None)):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if expected is not None:
                check(f"pg {table}", n, expected)
            else:
                print(f"  [--- ] pg {table}: {n} rows")
        dim = conn.execute("SELECT vector_dims(embedding) FROM chunks LIMIT 1").fetchone()
        if dim:
            check("pg chunks embedding dims", dim[0], 1536)

    from neo4j import GraphDatabase

    print("Neo4j counts:")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            for label, expected in manifest["nodes_by_label"].items():
                n = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS n").single()["n"]
                check(f"neo4j :{label}", n, expected)
            total = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
            print(f"  [--- ] neo4j total nodes: {total} (manifest content nodes: {manifest['nodes_total']})")
            for rtype, expected in manifest["relationships_by_type"].items():
                n = session.run(f"MATCH ()-[r:`{rtype}`]->() RETURN count(r) AS n").single()["n"]
                check(f"neo4j [:{rtype}]", n, expected)
    finally:
        driver.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", action="store_true")
    ap.add_argument("--db", action="store_true")
    ap.add_argument("--exports", type=Path, default=DEFAULT_EXPORTS)
    args = ap.parse_args()

    if not (args.files or args.db):
        args.files = True

    if args.files:
        verify_files(args.exports)
    if args.db:
        verify_db(args.exports)

    if FAILURES:
        print(f"\n{len(FAILURES)} MISMATCH(ES): {FAILURES}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
