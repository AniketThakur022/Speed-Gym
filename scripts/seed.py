#!/usr/bin/env python3
"""VMSG seed — idempotent dual-database import from the recovered db_exports.

Sources (incoming/topic_browser_full_package/db_exports/):
  chunks.jsonl        -> Postgres chunks           (4,943 rows, vector(1536))
  problems.jsonl      -> Postgres problems
  registry.jsonl      -> Postgres ontology_registry
  nodes.jsonl         -> Neo4j nodes    (MERGE on each label's export key)
  relationships.jsonl -> Neo4j edges    (MERGE, so re-runs don't duplicate)

Idempotent: Postgres uses ON CONFLICT DO NOTHING; Neo4j uses MERGE.
Run scripts/verify_seed.py --db afterwards to check counts vs the manifest.

Usage:
  python3 scripts/seed.py [--pg-only | --neo4j-only] [--exports DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORTS = ROOT / "incoming" / "topic_browser_full_package" / "db_exports"
CHUNK_TYPE_PATCH = ROOT / "data" / "factory" / "chunk_type_patch_v1.jsonl"

# Legacy pre-loss SymPy verifier v1 verdicts (documented 63.7% false-positive
# rate) — quarantined: never seeded as live fields. The real quality signal is
# the graph's validation_status (verified_L1/L2). See memory
# `neo4j-live-graph-schema` / coordinator note 2026-09-02.
QUARANTINED_FIELDS = {"python_audit_status", "_python_audit_status"}

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")

PG_BATCH = 200
NEO_BATCH = 500


def read_jsonl(path: Path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def batched(iterable, size):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def jdump(value):
    return json.dumps(value) if value is not None else None


def as_vector(value):
    """pgvector literal: exports carry embeddings as JSON lists (1536 floats)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "[" + ",".join(repr(float(v)) for v in value) + "]"


def seed_postgres(exports: Path) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        t0 = time.time()

        # ── chunks ────────────────────────────────────────────────────────
        # RAG's normalization patch overrides chunk_type per id (4,943 rows).
        type_patch: dict[str, str] = {}
        if CHUNK_TYPE_PATCH.exists():
            type_patch = {r["id"]: r["chunk_type"] for r in read_jsonl(CHUNK_TYPE_PATCH)}
            print(f"  chunk_type patch loaded: {len(type_patch)} overrides")

        n = 0
        with conn.cursor() as cur:
            for batch in batched(read_jsonl(exports / "chunks.jsonl"), PG_BATCH):
                cur.executemany(
                    """INSERT INTO chunks (id, book_id, page_number, chunk_type, content,
                           content_md, embedding, logic_bundle, station_audit,
                           schema_version, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s)
                       ON CONFLICT (id) DO NOTHING""",
                    [
                        (
                            r["id"], r.get("book_id"), r.get("page_number"),
                            type_patch.get(r["id"], r.get("chunk_type")),
                            r.get("content"), r.get("content_md"),
                            as_vector(r.get("embedding")),
                            jdump(r.get("logic_bundle") or {}),
                            jdump(r.get("station_audit") or {}),
                            r.get("schema_version"), r.get("created_at"),
                        )
                        for r in batch
                    ],
                )
                n += len(batch)
                conn.commit()
        print(f"  chunks: {n} processed ({time.time()-t0:.1f}s)")

        # ── problems ──────────────────────────────────────────────────────
        n = 0
        with conn.cursor() as cur:
            for batch in batched(read_jsonl(exports / "problems.jsonl"), PG_BATCH):
                cur.executemany(
                    """INSERT INTO problems (id, chunk_id, book_id, source_reference, chunk_idx,
                           record_type, topic, sub_topic, neo4j_problem_node_id,
                           neo4j_concept_cluster_name, neo4j_technique_name, neo4j_sutra_name,
                           problem_latex, problem_summary, logic_steps, raw_formulas,
                           answer_key_entry, answer_key_numeric, answer_key_latex,
                           answer_key_structured, target_variable, data_points,
                           verification_status, verification_error, verified_roots,
                           verified_at, verification_payload, difficulty_level, digit_size,
                           operation_type, strategy_type, is_multi_step, detected_traps,
                           required_skills, min_speed_level, lesson_node_id,
                           pedagogical_sequence_id, lesson_order, schema_version,
                           created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO NOTHING""",
                    [
                        (
                            r["id"], r.get("chunk_id"), r.get("book_id"),
                            str(r.get("source_reference")) if r.get("source_reference") is not None else None,
                            r.get("chunk_idx"), r.get("record_type"), r.get("topic"),
                            r.get("sub_topic"), r.get("neo4j_problem_node_id"),
                            r.get("neo4j_concept_cluster_name"), r.get("neo4j_technique_name"),
                            r.get("neo4j_sutra_name"), r.get("problem_latex"),
                            r.get("problem_summary"), jdump(r.get("logic_steps") or []),
                            jdump(r.get("raw_formulas") or []), r.get("answer_key_entry"),
                            r.get("answer_key_numeric"), r.get("answer_key_latex"),
                            jdump(r.get("answer_key_structured")), r.get("target_variable"),
                            jdump(r.get("data_points") or {}), r.get("verification_status"),
                            r.get("verification_error"), jdump(r.get("verified_roots") or []),
                            r.get("verified_at"), jdump(r.get("verification_payload")),
                            r.get("difficulty_level"), r.get("digit_size"),
                            r.get("operation_type"), r.get("strategy_type"),
                            bool(r.get("is_multi_step")), jdump(r.get("detected_traps") or []),
                            jdump(r.get("required_skills") or []), r.get("min_speed_level"),
                            r.get("lesson_node_id"), r.get("pedagogical_sequence_id"),
                            r.get("lesson_order"), r.get("schema_version"),
                            r.get("created_at"), r.get("updated_at"),
                        )
                        for r in batch
                    ],
                )
                n += len(batch)
                conn.commit()
        print(f"  problems: {n} processed")

        # ── ontology registry ─────────────────────────────────────────────
        n = 0
        with conn.cursor() as cur:
            for batch in batched(read_jsonl(exports / "registry.jsonl"), PG_BATCH):
                cur.executemany(
                    """INSERT INTO ontology_registry (id, label, category, description,
                           embedding, aliases, source_book, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s::vector,%s,%s,%s,%s)
                       ON CONFLICT (id) DO NOTHING""",
                    [
                        (
                            r["id"], r["label"], r.get("category"), r.get("description"),
                            as_vector(r.get("embedding")), jdump(r.get("aliases") or []),
                            r.get("source_book"), r.get("created_at"), r.get("updated_at"),
                        )
                        for r in batch
                    ],
                )
                n += len(batch)
                conn.commit()
        print(f"  ontology_registry: {n} processed")

        conn.execute("ANALYZE chunks")
        conn.commit()


def seed_neo4j(exports: Path) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            # ── nodes: group by (label, key_field) so MERGE keys are stable ──
            groups: dict[tuple[str, str], list[dict]] = {}
            for r in read_jsonl(exports / "nodes.jsonl"):
                label, key_field = r["_label"], r["_key_field"]
                props = {
                    k: v
                    for k, v in r.items()
                    if not k.startswith("_") and v is not None and k not in QUARANTINED_FIELDS
                }
                props[key_field] = r["_key_value"]
                groups.setdefault((label, key_field), []).append(props)

            total = 0
            for (label, key_field), rows in sorted(groups.items()):
                q = (
                    f"UNWIND $rows AS row "
                    f"MERGE (n:`{label}` {{`{key_field}`: row.`{key_field}`}}) "
                    f"SET n += row"
                )
                for batch in batched(rows, NEO_BATCH):
                    session.run(q, rows=batch).consume()
                total += len(rows)
                print(f"  nodes {label} (key {key_field}): {len(rows)}")
            print(f"  nodes total: {total}")

            # ── relationships: group by full shape ───────────────────────────
            rel_groups: dict[tuple, list[dict]] = {}
            for r in read_jsonl(exports / "relationships.jsonl"):
                key = (
                    r["start_label"], r["start_key_field"], r["rel_type"],
                    r["end_label"], r["end_key_field"],
                )
                rel_groups.setdefault(key, []).append(
                    {"start": r["start_key"], "end": r["end_key"], "props": r.get("properties") or {}}
                )

            total = 0
            for (sl, sk, rt, el, ek), rows in sorted(rel_groups.items()):
                q = (
                    f"UNWIND $rows AS row "
                    f"MATCH (a:`{sl}` {{`{sk}`: row.start}}) "
                    f"MATCH (b:`{el}` {{`{ek}`: row.end}}) "
                    f"MERGE (a)-[r:`{rt}`]->(b) "
                    f"SET r += row.props"
                )
                for batch in batched(rows, NEO_BATCH):
                    session.run(q, rows=batch).consume()
                total += len(rows)
                print(f"  rels {sl}-[{rt}]->{el}: {len(rows)}")
            print(f"  relationships total: {total}")

            # Pre-create the 3 Skill nodes for the 54 newly recovered Dhvajanka
            # templates (never in the 2026-06-03 export; 26 chain mentions in
            # RAG's derived REQUIRES edges reference them — their loader
            # factory/closure/load_requires_edges.cypher MERGE-matches these).
            for name in ("Dhvajanka Sutra Level 1", "Dhvajanka Sutra Level 2", "Dhvajanka Sutra Level 3"):
                session.run(
                    "MERGE (s:Skill {name: $name}) "
                    "ON CREATE SET s.name_norm = toLower($name), s.topic = 'VedicMath', "
                    "s.source = 'recovered_2026-09-02', s.is_root = false, s.is_stub = false",
                    name=name,
                ).consume()
            print("  Dhvajanka Level 1-3 :Skill nodes ensured (RAG MERGE-window prereq)")
    finally:
        driver.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-only", action="store_true")
    ap.add_argument("--neo4j-only", action="store_true")
    ap.add_argument("--exports", type=Path, default=DEFAULT_EXPORTS)
    args = ap.parse_args()

    if not args.exports.exists():
        print(f"exports dir not found: {args.exports}", file=sys.stderr)
        return 1

    if not args.neo4j_only:
        print("Seeding Postgres ...")
        seed_postgres(args.exports)
    if not args.pg_only:
        print("Seeding Neo4j ...")
        seed_neo4j(args.exports)
    print("done — run scripts/verify_seed.py --db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
