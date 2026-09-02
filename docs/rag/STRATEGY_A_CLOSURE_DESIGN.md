# Prerequisite-closure precompute — Strategy A, adapted to the live graph

**Workstream:** Speed Gym RAG · **Date:** 2026-09-02
**Inputs:** `incoming/topic_browser_full_package/db_exports/` (manifest dated 2026-06-03: 3,585 nodes / 8,678 rels — the real GPS export), `docs/reference/pipeline-untitled.pdf` (Strategies A–D)
**Goal:** app answers "what must the student know before X?" from Postgres `prerequisite_closure`; Neo4j is never traversed at runtime.

## 1. The closure PDF's premise does not hold on the live graph

The PDF assumes a transitive `(:Technique)-[:PREREQUISITE_OF]->(:Technique)` graph and prescribes `apoc.path.spanningTree` over `PREREQUISITE_OF>`. Measured reality (full tabulation of `relationships.jsonl`):

| Edge | Live domain → range | Count | Semantics (verified by sampling) |
|---|---|---|---|
| `PREREQUISITE_OF` | **Skill → Problem** | 2,457 | Q-matrix: skill needed to solve problem. **Bipartite, depth-1, no transitivity.** |
| `FRONTIER_OF` | Skill → Skill | 2,678 | **100% reciprocal pairs** (= 1,339 undirected edges), all `inferred:true`. Adjacency/similarity, NOT ordering. Traversing it transitively floods the connected component. |
| `NEXT_TOPIC` | Skill → Skill | 82 | curriculum sequence, **earlier → later** (`Linear Equations → Quadratic Equations`) |
| `REQUIRES` | Skill → Skill | 11 | **dependent → prerequisite** (`VedicMath → Arithmetic`) |

So the transitive skill-ordering layer is only **93 directed edges over 467 skills** — the "2,457 prerequisite links" celebrated in the content-readiness doc are the Skill→Problem Q-matrix, not a skill DAG. **A naïve Strategy A port would return either almost nothing (93 edges) or garbage (flooding via reciprocal FRONTIER_OF).** Both PDFs' Cypher (`:Technique`, undirected assumptions) must not be copied.

## 2. Step 0 (new, required): derive the canonical Skill→Skill DAG

Deterministic, no-AI derivation from recovered data, written as `REQUIRES` edges (dependent → prerequisite; the 11 existing curated edges already have exactly these semantics — we extend that relation rather than overloading `PREREQUISITE_OF`, which stays Skill→Problem):

1. **Template chains (set semantics — REVISED after sampling):** every recovered template carries a `prerequisite_chain` (2,863 entries; 91% resolve exactly to live `:Skill.name`). Sampling shows chains are **unordered prerequisite sets** (broad→specific-ish, with sutras sometimes listed before basics), so consecutive-pair derivation is unsafe. Rule: resolve the template's taught skill **S** (its `sub_topic` when it names a live Skill — 772/915 records; else the `TEACHES` edge — 307, but coarse; else `technique_name` via `name_norm`), then emit `S REQUIRES member` for each resolved chain member, no chain-internal pairs, no self-loops. Aggregate over the 861 unique templates; keep edges with support ≥2 (noise floor), tag `source:'chain_derived', support:<n>`. Transitive depth still emerges because chain members are themselves taught skills of other templates.
2. **Curated sequence:** invert `NEXT_TOPIC` (82) into `later REQUIRES earlier`, tag `source:'next_topic'`.
3. **Keep** the 11 hand-curated `REQUIRES`, tag `source:'curated'` (highest precedence).
4. **Root guard (derived edges only):** chain-derived edges FROM one of the 9 `is_root` skills are dropped — noisy chains must not give roots new dependencies. Curated edges are exempt (`VedicMath REQUIRES Arithmetic` is legitimate and stays).
5. **Cycle break:** the builder runs SCC detection on the final edge set and breaks cycles by removing the lowest-`support` derived edge per cycle, logging every removal to the run report. Curated/next_topic edges are never auto-removed.
6. **Name resolution:** unresolved chain strings (~9%) resolve via `name_norm` casefold matching and `ontology_registry.yaml` aliases; the remainder are dropped and reported (no stub-node creation until the owner reviews the unresolved list).
7. `FRONTIER_OF` is **never** used for closure. It remains the sibling/adjacency signal for the hourly T3 bridge (1-hop "sibling subtopic" pulls).

## 3. Strategy A proper (per the PDF, corrected labels/filters)

Per-skill bounded BFS, APOC (built into AuraDB Free):

```cypher
// Start from every skill with outgoing REQUIRES — stubs included (verified in the
// 2026-09-02 merge window: stub-seeded skills like 'Division' are legitimate
// closure targets; filtering them caused a 23-row shadow-diff miss).
MATCH (s:Skill) WHERE (s)-[:REQUIRES]->()
CALL apoc.path.spanningTree(s, {
  relationshipFilter: "REQUIRES>",
  minLevel: 1, maxLevel: 5, limit: 1000
}) YIELD path
RETURN s.name AS descendant,
       last(nodes(path)).name AS ancestor,
       length(path) AS depth
```

- Batched 100 start-nodes per query (`SKIP/LIMIT` on an ordered skill list), single writer to Postgres via `psycopg2 execute_values`, per-batch commit — the PDF's Strategy-B batching hygiene applied from day 1, cheap insurance.
- **Scale check (measured):** 467 skills, ≈1–2k derived REQUIRES edges; worst-case closure 467² ≈ 218k rows — trivially within the PDF's thresholds (<70% heap, <30s, <5MB/batch). The ~15k-node Strategy-A wall is ~30× away; Strategies B/C stay on the shelf per the phased plan (topic property for B already exists on every Skill node).

## 4. Postgres landing zone (Ledger)

```sql
CREATE TABLE prerequisite_closure (
  descendant_skill TEXT NOT NULL,   -- the skill being asked about
  ancestor_skill   TEXT NOT NULL,   -- must be known first
  depth            SMALLINT NOT NULL CHECK (depth BETWEEN 1 AND 5),
  min_depth        SMALLINT NOT NULL,          -- MIN over paths (PDF Strategy-C convention)
  support          SMALLINT NOT NULL DEFAULT 1,
  computed_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (descendant_skill, ancestor_skill)
);
CREATE INDEX ON prerequisite_closure (descendant_skill, min_depth);

CREATE TABLE problem_requirements (        -- depth-1 Q-matrix export of PREREQUISITE_OF
  skill_name  TEXT NOT NULL,
  template_id TEXT NOT NULL,               -- :Problem key
  PRIMARY KEY (skill_name, template_id)
);
```

Plus the PDF's benchmark protocol verbatim: `prerequisite_closure_test` shadow table, `sync_manifest` (source, target_table, status dry_run/production, timings, memory, error), `benchmark_closure_strategies.py`. First run goes `dry_run` into the shadow table and diffs before promoting.

**App query** ("everything needed before X, nearest first"):
`SELECT ancestor_skill, min_depth FROM prerequisite_closure WHERE descendant_skill = $1 ORDER BY min_depth;`
Problem-readiness = `problem_requirements ⋈ prerequisite_closure` — both Postgres-only. Game-loop isolation holds: closure is precomputed in the nightly factory window, never at practice time.

## 5. Build order & open confirmations

1. DAG builder (chain derivation + validation report: edge counts by source, SCC report, root guard) — runs offline from the export files now; MERGE into live Neo4j once backend re-seeds it.
2. Strategy A extractor → shadow table → benchmark → promote.
3. Nightly delta: re-run full closure after each factory run that adds Skills/edges (full recompute is seconds at this scale; Strategy D incrementalism unnecessary until the graph ~10×).
4. **Confirm with backend chat:** hosting (AuraDB Free vs droplet — APOC availability assumed either way), and the Celery task names the nightly step hangs off.
5. **Confirm with owner once:** extending `REQUIRES` as the canonical skill-DAG relation (vs renaming) — recorded in `neo4j-live-graph-schema` memory.
