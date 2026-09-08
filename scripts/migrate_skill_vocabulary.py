#!/usr/bin/env python3
"""Repair the :Skill vocabulary — case duplicates, structural names, namespaced
stub variants, and the Basic Operations cluster — as ONE idempotent migration.

    python3 scripts/migrate_skill_vocabulary.py --dry-run     # plan + manifest, no writes
    python3 scripts/migrate_skill_vocabulary.py               # apply
    python3 scripts/migrate_skill_vocabulary.py --promote-closure   # also promote the shadow

WHY THIS SCRIPT PINS BEFORE IT RENAMES
--------------------------------------
Mastery is keyed on :Skill.name, and services/api/app/routers/session.py derives
that key by taking the alphabetically-first skill parent of a problem (after
demoting structural names). 746 of 766 servable problems have 2-7 parents, so the
key is decided by a STRING SORT among siblings. Neo4j orders by codepoint, so
'D'(68) < 'F'(70) < 'a'(97): recasing ANY skill can silently move the key of a
problem that skill does not currently key.

Measured on the live graph, the merges below move 12 of 766 keys, and only 7 of
those are expressible as old-name -> new-name:
  * Bird_Engineering_Math_sa_187 loses 'Angle and Side Relationships' — a node
    that is NOT renamed, NOT deleted and NOT in any duplicate group — purely
    because the sibling 'Angle measurement' was recased.
  * Bird_Engineering_Math_sa_45 jumps 'Fractions and Decimals' -> 'Decimals',
    a different skill, for the same reason.
  * 'Fractions and Decimals' 3->2 and 'Basic Operations' 92->94 SPLIT rather
    than vanish, which a vanish/appear diff cannot see at all.
A name->name remap therefore cannot express this migration. So step 1 freezes
today's attribution onto :Problem.mastery_key BEFORE anything moves, and every
later step maintains that pin explicitly. session.py then reads
`coalesce(p.mastery_key, <sorted pick>)`, which makes every future vocabulary
edit a display change instead of an unbounded mastery-schema change. That matters:
renaming 'Basic Operations (+, -, x, /)' alone could capture 183 problems it does
not key today — 36% of the servable pool — in a single edit.

Doing this NOW is free: every per-problem attribution table is empty, and the only
real user state keys on 'nikhilam' (not a :Skill) and 'Basic number sense'
(untouched here). After learners accumulate state it stops being free.

WHAT IT DOES NOT DO
-------------------
It does not delete stubs. 374 of 470 skills are is_stub, ALL of them carry
PREREQUISITE_OF edges, and deleting them changes 119 of 766 mastery keys, strands
45 problems with no skill parent, and collapses the key vocabulary from 116 to 28.
Only the provable subset is repaired: a stub named '<root topic><sep><name of an
existing :Skill>' is a namespacing artifact, not a concept. 18 of the 20 such
stubs resolve; the other ~356 stubs are reported, not touched.

It does not rewrite raw_events.metadata. That is an append-only event ledger; its
rows record what the client actually sent at the time, and rewriting them would
falsify history that replay depends on.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")

SOURCE = "scripts/migrate_skill_vocabulary.py"
REPORT_DIR = ROOT / "data" / "migrations"

# Factory artefacts. factory/closure/live_load.py PRUNES any REQUIRES edge that
# skill_requires_edges_v1.jsonl no longer asserts, TRUNCATEs problem_requirements
# and reloads it from problem_requirements_v1.jsonl, and refuses to promote the
# closure unless the live result matches prerequisite_closure_v1.jsonl EXACTLY.
# So a merge that does not rewrite these three files is silently reverted the
# next time RAG runs its loader. Keeping them in step is the coordination.
FACTORY_DIR = ROOT / "data" / "factory"
F_EDGES = FACTORY_DIR / "skill_requires_edges_v1.jsonl"
F_CLOSURE = FACTORY_DIR / "prerequisite_closure_v1.jsonl"
F_QMATRIX = FACTORY_DIR / "problem_requirements_v1.jsonl"

# The exact pattern session.py uses today to demote structural names in the pick.
STRUCTURAL_RE_SESSION = (
    r"(?i)^\s*(chapter|ch\.?|section|sec\.?|unit|part|exercise|ex\.?|lesson)"
    r"\s*[0-9ivxl.]*\s*$|^\s*[0-9.]+\s*$"
)

# Structural :Skill names to remove. An EXPLICIT allowlist, not a regex sweep.
# A regex loose enough to catch 'Chapter on Cubing Numbers' also catches
# 'Unit Circle', 'Unit Conversion' and 'Vyashti Samashti (Part and Whole)',
# which are real concepts; deleting those would destroy vocabulary. Each name
# here was hand-checked against the live graph, and the migration re-verifies at
# runtime that every problem underneath keeps another skill parent.
STRUCTURAL_DELETE = [
    "Chapter 11",                                        # book chapter heading
    "Chapter 11 on simple equations",                    # ditto, missed by the regex
    "Chapter on Cubing Numbers",                         # ditto
    "Advance Level",                                     # difficulty band heading
    "Previous sutras (referencing crosswise subtraction)",  # anaphoric cross-reference
]

# The Basic Operations cluster, as handed over by the RAG chat. Listed explicitly
# rather than derived, because 'Arithmetic:Basic Operations' has no bare concept
# to resolve to and would otherwise be missed.
BASIC_OPS_SURVIVOR = "Basic Operations (+, -, ×, ÷)"
BASIC_OPS_ABSORB = [
    "Arithmetic: Basic Operations (+, -, ×, ÷)",
    "Arithmetic:Basic Operations (+, -, ×, ÷)",
    "Arithmetic:Basic Operations",
]

# Relationship types a :Skill participates in. Used to move edges off a loser.
SKILL_RELS = [
    "PREREQUISITE_OF", "REQUIRES", "FRONTIER_OF", "NEXT_TOPIC",
    "TEACHES", "EXPLAINS", "MANIFESTS_AS", "HAS_SKILL_LEVEL",
]

# Postgres columns holding a bare skill key, as (table, column, conflict_key).
# conflict_key is the unique tuple a rename can collide on, or None when the
# column carries no uniqueness and a plain UPDATE is safe.
PG_KEY_COLUMNS = [
    ("user_technique_states", "technique_id", ("user_id", "technique_id")),
    ("skill_progression_daily", "technique_id", ("user_id", "technique_id", "date")),
    ("sinking_skills", "technique_id", ("user_id", "technique_id")),
    ("sinking_skills", "technique_canonical_id", None),
    ("technique_state_transitions", "technique_id", None),
]

# JSONB objects keyed BY skill name (the key is the skill, not a value).
PG_JSONB_KEYED = [
    ("bkt_state_snapshots", "technique_states", None),
    ("sync_outbox", "payload", "status = 'pending'"),
]


def log(msg: str = "") -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# planning — read-only
# --------------------------------------------------------------------------

def title_score(name: str) -> int:
    """How Title-Case-ish a name is: count of words starting with a capital."""
    return sum(1 for w in name.split() if w[:1].isupper())


def survivor_rank(node: dict) -> tuple:
    """Lower sorts better. The survivor keeps its NAME; the loser's edges are all
    moved onto it, so edge counts are NOT a tiebreak — nothing is lost either way.
    What the choice actually decides is which string becomes canonical, so prefer
    the node the rest of the system knows something about, then the better-cased
    string, then lexicographic for determinism."""
    return (
        1 if node.get("is_stub") else 0,
        0 if node.get("topic") else 1,
        0 if node.get("source") else 1,
        -title_score(node["name"]),
        0 if node["name"][:1].isupper() else 1,
        node["name"],
    )


def build_plan(neo) -> dict:
    """Compute every rename/delete from the live graph. Pure read."""
    nodes = {
        r["name"]: r
        for r in neo.run(
            """MATCH (s:Skill)
               OPTIONAL MATCH (s)-[:PREREQUISITE_OF]->(p:Problem)
               RETURN s.name AS name, s.is_stub AS is_stub, s.topic AS topic,
                      s.sub_topic AS sub_topic, s.source AS source,
                      s.is_root AS is_root, count(p) AS problems"""
        )
    }
    roots = {n for n, r in nodes.items() if r.get("is_root")}
    # The 9 topic roots are the legitimate namespace prefixes. Read them from the
    # graph rather than hard-coding, so a re-run after a taxonomy change is right.
    roots |= {r["topic"] for r in nodes.values() if r.get("topic")}

    merges: dict[str, str] = {}          # loser -> survivor
    reasons: dict[str, str] = {}
    groups: list[dict] = []

    # --- defect 1: case duplicates -------------------------------------
    by_lower: dict[str, list[dict]] = defaultdict(list)
    for r in nodes.values():
        by_lower[r["name"].lower()].append(r)
    for key, members in sorted(by_lower.items()):
        if len(members) < 2:
            continue
        ranked = sorted(members, key=survivor_rank)
        survivor = ranked[0]["name"]
        losers = [m["name"] for m in ranked[1:]]
        groups.append({"defect": "case_duplicate", "key": key,
                       "survivor": survivor, "losers": losers})
        for l in losers:
            merges[l] = survivor
            reasons[l] = "case_duplicate"

    # --- defect 3 (tractable subset) + defect 4: namespaced variants ----
    # A stub named '<root topic><sep><name of an existing :Skill>' is a
    # namespacing artifact. Anything that does not resolve is left alone.
    for name, r in sorted(nodes.items()):
        if ":" not in name or name in merges:
            continue
        prefix, _, bare = name.partition(":")
        prefix, bare = prefix.strip(), bare.strip()
        if prefix not in roots or not bare:
            continue
        target = bare if bare in nodes else next(
            (n for n in nodes if n.lower() == bare.lower()), None)
        if not target or target == name:
            continue
        merges[name] = target
        reasons[name] = "namespaced_variant"
        groups.append({"defect": "namespaced_variant", "key": name,
                       "survivor": target, "losers": [name]})

    # --- defect 4: the RAG-supplied Basic Operations cluster ------------
    for loser in BASIC_OPS_ABSORB:
        if loser in nodes and loser != BASIC_OPS_SURVIVOR:
            merges[loser] = BASIC_OPS_SURVIVOR
            reasons[loser] = "basic_operations_cluster"
    if BASIC_OPS_SURVIVOR in nodes:
        groups.append({
            "defect": "basic_operations_cluster", "key": BASIC_OPS_SURVIVOR,
            "survivor": BASIC_OPS_SURVIVOR,
            "losers": [n for n in BASIC_OPS_ABSORB if n in nodes]})

    # --- defect 2: structural names ------------------------------------
    deletes = [n for n in STRUCTURAL_DELETE if n in nodes]

    # Resolve chains (a loser whose survivor is itself a loser) so the map is
    # single-hop and order-independent.
    def resolve(name: str, seen=None) -> str:
        seen = seen or set()
        while name in merges and name not in seen:
            seen.add(name)
            name = merges[name]
        return name

    merges = {l: resolve(s) for l, s in merges.items()}
    # A survivor must never also be a delete target, and vice versa.
    conflicts = [l for l, s in merges.items() if s in deletes] + \
                [d for d in deletes if d in merges]

    return {"nodes": nodes, "merges": merges, "reasons": reasons,
            "groups": groups, "deletes": deletes, "conflicts": conflicts}


def compute_pick(parents: list[str]) -> str | None:
    """Reproduce session.py's mastery-key pick in Python, byte-for-byte:
    demote structural names, then take the codepoint-first name."""
    if not parents:
        return None
    rx = re.compile(STRUCTURAL_RE_SESSION)
    return sorted(set(parents), key=lambda n: (1 if rx.fullmatch(n) else 0, n))[0]


def key_delta(neo, plan: dict) -> list[dict]:
    """Before/after mastery key for every problem, driven by the parent SETS —
    not by a name map, because a key can move without its own name changing."""
    rows = [
        r for r in neo.run(
            """MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
               RETURN p.template_id AS tid, collect(s.name) AS parents"""
        )
    ]
    merges, deletes = plan["merges"], set(plan["deletes"])
    out = []
    for r in rows:
        before = compute_pick(r["parents"])
        after_parents = [merges.get(n, n) for n in r["parents"] if n not in deletes]
        after = compute_pick(after_parents)
        if before == after:
            continue
        if after is None:
            cause = "unservable"
        elif before in deletes:
            cause = "deleted_reattributed"
        elif before in merges:
            cause = "renamed"
        else:
            cause = "silent_sibling_reorder"
        out.append({"template_id": r["tid"], "old_key": before,
                    "new_key": after, "cause": cause})
    return sorted(out, key=lambda x: x["template_id"])


# --------------------------------------------------------------------------
# apply — Neo4j
# --------------------------------------------------------------------------

def pin_mastery_keys(neo, dry: bool) -> int:
    """Freeze today's attribution onto :Problem.mastery_key.

    coalesce() makes this a no-op on re-run, and it covers ALL problems with a
    skill parent, not just the currently servable ones — a problem whose
    answer_key is filled in later would otherwise become servable with an
    unpinned key and reopen the same hazard."""
    q = """MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
           WITH p, s ORDER BY (CASE WHEN s.name =~ $rx THEN 1 ELSE 0 END), s.name
           WITH p, head(collect(s.name)) AS k
           WHERE p.mastery_key IS NULL
           %s
           RETURN count(*) AS n"""
    if dry:
        return neo.run(q % "", rx=STRUCTURAL_RE_SESSION).single()["n"]
    return neo.run(q % "SET p.mastery_key = k", rx=STRUCTURAL_RE_SESSION).single()["n"]


def merge_skill(neo, loser: str, survivor: str) -> dict:
    """Move every edge off `loser` onto `survivor`, then delete `loser`.

    MERGE gives dedup for free (23 FRONTIER_OF, 18 EXPLAINS, 11 TEACHES, 4
    REQUIRES and 1 PREREQUISITE_OF collision on the live data). Properties come
    across ON CREATE only: when the MERGE lands on an edge the survivor already
    has, that edge keeps its own properties — otherwise a stub's derived
    `source`/`support` would clobber a curated REQUIRES edge. And the
    endpoint check drops the self-loops a merge would otherwise create (2
    FRONTIER_OF in the 'negative angle identities' group, 4 inside the Basic
    Operations cluster). Properties transfer only where the survivor has none,
    so a merge never overwrites curated metadata with a stub's nulls."""
    stats: dict[str, int] = {}
    tx = neo.begin_transaction()
    for rel in SKILL_RELS:
        for direction in ("out", "in"):
            if direction == "out":
                pattern = f"(l)-[r:{rel}]->(o)"
                create = f"(sv)-[n:{rel}]->(o)"
            else:
                pattern = f"(o)-[r:{rel}]->(l)"
                create = f"(o)-[n:{rel}]->(sv)"
            res = tx.run(
                f"""MATCH (l:Skill {{name:$loser}}), (sv:Skill {{name:$survivor}})
                    MATCH {pattern}
                    WHERE o <> sv
                    MERGE {create}
                    ON CREATE SET n += properties(r)
                    DELETE r
                    RETURN count(*) AS n""",
                loser=loser, survivor=survivor,
            ).single()["n"]
            if res:
                stats[f"{rel}_{direction}"] = res
    # Anything left is a self-loop-to-be (loser <-> survivor); drop it.
    dropped = tx.run(
        """MATCH (l:Skill {name:$loser})-[r]-() RETURN count(r) AS n""",
        loser=loser).single()["n"]
    if dropped:
        stats["self_loops_dropped"] = dropped
    # Carry properties the survivor lacks, then remove the node.
    tx.run(
        """MATCH (l:Skill {name:$loser}), (sv:Skill {name:$survivor})
           SET sv.topic      = coalesce(sv.topic, l.topic),
               sv.sub_topic  = coalesce(sv.sub_topic, l.sub_topic),
               sv.source     = coalesce(sv.source, l.source),
               sv.is_root    = coalesce(sv.is_root, l.is_root)
           DETACH DELETE l""",
        loser=loser, survivor=survivor)
    tx.commit()
    return stats


def delete_structural(neo, name: str, check_only: bool = False) -> dict:
    """Delete a structural node, refusing if any problem would lose its last
    skill parent. Checked at runtime, not trusted from the plan — and checked in
    --dry-run too, so the dry run can fail for the same reason the real one would."""
    stranded = [
        r["tid"] for r in neo.run(
            """MATCH (s:Skill {name:$name})-[:PREREQUISITE_OF]->(p:Problem)
               WHERE NOT EXISTS {
                 MATCH (o:Skill)-[:PREREQUISITE_OF]->(p) WHERE o.name <> $name }
               RETURN p.template_id AS tid""", name=name)
    ]
    if stranded:
        raise SystemExit(
            f"REFUSING to delete structural :Skill {name!r}: it is the only skill "
            f"parent of {len(stranded)} problem(s) {stranded[:5]}. Re-point them first.")
    counts = neo.run(
        "MATCH (s:Skill {name:$name})-[r]-() RETURN type(r) AS t, count(*) AS n",
        name=name)
    stats = {r["t"]: r["n"] for r in counts}
    if not check_only:
        neo.run("MATCH (s:Skill {name:$name}) DETACH DELETE s", name=name)
    return stats


def repoint_pins(neo, plan: dict, dry: bool) -> dict:
    """Maintain the pin across the merges: a pinned key naming a merged-away
    skill follows it; a pinned key naming a deleted structural skill is
    recomputed from the surviving parents."""
    merges, deletes = plan["merges"], set(plan["deletes"])
    if dry:
        # Nothing was pinned, so count against the key step 1 would have written.
        picks = [
            compute_pick(r["parents"]) for r in neo.run(
                """MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
                   RETURN p.template_id AS tid, collect(s.name) AS parents""")
        ]
        return {"renamed": sum(1 for k in picks if k in merges),
                "recomputed": sum(1 for k in picks if k in deletes)}
    merges, deletes = plan["merges"], plan["deletes"]
    n_ren = neo.run(
        """UNWIND keys($m) AS old
           MATCH (p:Problem {mastery_key: old})
           SET p.mastery_key = $m[old]
           RETURN count(*) AS n""", m=merges).single()["n"]
    n_del = neo.run(
        """UNWIND $d AS old
           MATCH (p:Problem {mastery_key: old})
           OPTIONAL MATCH (s:Skill)-[:PREREQUISITE_OF]->(p)
           WITH p, s ORDER BY (CASE WHEN s.name =~ $rx THEN 1 ELSE 0 END), s.name
           WITH p, head(collect(s.name)) AS k
           SET p.mastery_key = k
           RETURN count(*) AS n""",
        d=deletes, rx=STRUCTURAL_RE_SESSION).single()["n"]
    return {"renamed": n_ren, "recomputed": n_del}


# --------------------------------------------------------------------------
# apply — Postgres
# --------------------------------------------------------------------------

def migrate_pg_keys(cur, plan: dict, dry: bool) -> dict:
    """Rewrite every Postgres surface holding a bare skill key.

    Renames can collide on a unique key (a user holding state under BOTH the
    survivor and a loser). Collisions are never silently merged: the survivor's
    row is kept, the loser's is dropped, and every one is reported."""
    merges, deletes = plan["merges"], plan["deletes"]
    pairs = list(merges.items())
    out: dict[str, dict] = {}

    for table, col, conflict in PG_KEY_COLUMNS:
        stats = {"updated": 0, "collisions": 0, "deleted_structural": 0}
        for old, new in pairs:
            if conflict:
                others = " AND ".join(
                    f"t.{c} IS NOT DISTINCT FROM x.{c}" for c in conflict if c != col)
                cur.execute(
                    f"SELECT count(*) FROM {table} t WHERE t.{col} = %s AND EXISTS ("
                    f"  SELECT 1 FROM {table} x WHERE x.{col} = %s"
                    + (f" AND {others}" if others else "") + ")", (old, new))
                collided = cur.fetchone()[0]
                stats["collisions"] += collided
                if not dry and collided:
                    cur.execute(
                        f"DELETE FROM {table} t WHERE t.{col} = %s AND EXISTS ("
                        f"  SELECT 1 FROM {table} x WHERE x.{col} = %s"
                        + (f" AND {others}" if others else "") + ")", (old, new))
            cur.execute(f"SELECT count(*) FROM {table} WHERE {col} = %s", (old,))
            n = cur.fetchone()[0]
            if n and not dry:
                cur.execute(f"UPDATE {table} SET {col} = %s WHERE {col} = %s", (new, old))
            stats["updated"] += n
        for gone in deletes:
            cur.execute(f"SELECT count(*) FROM {table} WHERE {col} = %s", (gone,))
            stats["deleted_structural"] += cur.fetchone()[0]
        if any(stats.values()):
            out[f"{table}.{col}"] = stats

    # JSONB objects KEYED by skill name. `- old || jsonb_build_object(new, ...)`
    # is idempotent: after the first pass the row no longer has `old`, so the
    # WHERE clause stops matching it.
    for table, col, extra in PG_JSONB_KEYED:
        # Two Postgres traps in one expression: `jsonb -> 'x'` is ambiguous
        # between the text and integer overloads (hence ::text), and arithmetic
        # `-` binds TIGHTER than `->`, so without the parentheses
        # `payload -> 'technique_states' - $1` parses as
        # `payload -> ('technique_states' - $1)` and fails on `text - text`.
        obj = col if col == "technique_states" else f"({col} -> 'technique_states'::text)"
        where_extra = f" AND {extra}" if extra else ""
        stats = {"rewritten": 0, "collisions": 0}
        for old, new in pairs:
            cur.execute(
                f"SELECT count(*) FROM {table} WHERE {obj} ? %s::text{where_extra}", (old,))
            n = cur.fetchone()[0]
            if not n:
                continue
            cur.execute(
                f"SELECT count(*) FROM {table} WHERE {obj} ? %s::text AND {obj} ? %s::text{where_extra}",
                (old, new))
            coll = cur.fetchone()[0]
            stats["rewritten"] += n
            stats["collisions"] += coll
            if dry:
                continue
            # Every jsonb operand needs an explicit ::text cast — `jsonb - $1`
            # is ambiguous between the text and int overloads otherwise.
            if col == "technique_states":
                cur.execute(
                    f"UPDATE {table} SET {col} = "
                    f"  CASE WHEN {col} ? %s::text THEN {col} - %s::text "
                    f"       ELSE ({col} - %s::text) "
                    f"            || jsonb_build_object(%s::text, {col} -> %s::text) END "
                    f"WHERE {col} ? %s::text{where_extra}",
                    (new, old, old, new, old, old))
            else:
                cur.execute(
                    f"UPDATE {table} SET {col} = jsonb_set({col}, '{{technique_states}}', "
                    f"  CASE WHEN {obj} ? %s::text THEN {obj} - %s::text "
                    f"       ELSE ({obj} - %s::text) "
                    f"            || jsonb_build_object(%s::text, {obj} -> %s::text) END) "
                    f"WHERE {obj} ? %s::text{where_extra}",
                    (new, old, old, new, old, old))
        if any(stats.values()):
            out[f"{table}.{col}[jsonb]"] = stats
    return out


def repoint_qmatrix(cur, plan: dict, dry: bool) -> dict:
    """Re-point problem_requirements. PRIMARY KEY (skill_name, template_id)
    collides whenever survivor and loser both require the same template — 1 such
    pair on the live data — so the duplicate is dropped, not upserted."""
    merges, deletes = plan["merges"], plan["deletes"]
    stats = {"updated": 0, "collisions": 0, "deleted_structural": 0}
    for old, new in merges.items():
        cur.execute(
            "SELECT count(*) FROM problem_requirements a WHERE a.skill_name = %s "
            "AND EXISTS (SELECT 1 FROM problem_requirements b "
            "            WHERE b.skill_name = %s AND b.template_id = a.template_id)",
            (old, new))
        coll = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM problem_requirements WHERE skill_name = %s", (old,))
        n = cur.fetchone()[0]
        stats["collisions"] += coll
        stats["updated"] += n - coll
        if dry or not n:
            continue
        cur.execute(
            "DELETE FROM problem_requirements a WHERE a.skill_name = %s "
            "AND EXISTS (SELECT 1 FROM problem_requirements b "
            "            WHERE b.skill_name = %s AND b.template_id = a.template_id)",
            (old, new))
        cur.execute(
            "UPDATE problem_requirements SET skill_name = %s WHERE skill_name = %s",
            (new, old))
    for gone in deletes:
        cur.execute("SELECT count(*) FROM problem_requirements WHERE skill_name = %s", (gone,))
        stats["deleted_structural"] += cur.fetchone()[0]
        if not dry:
            cur.execute("DELETE FROM problem_requirements WHERE skill_name = %s", (gone,))
    return stats


def closure_from_edges(edges) -> list[tuple]:
    """BFS to depth 5 over dependent->prerequisite edges, keeping MIN depth.
    Same semantics as apoc.path.spanningTree('REQUIRES>', maxLevel 5) and as
    factory/closure/build_closure.py, so the three agree row for row."""
    adj = defaultdict(list)
    nodes = set()
    for f, t in edges:
        adj[f].append(t)
        nodes.update((f, t))
    rows = []
    for start in sorted(nodes):
        depth, queue = {start: 0}, [start]
        while queue:
            v = queue.pop(0)
            if depth[v] >= 5:
                continue
            for w in adj.get(v, ()):
                if w not in depth:
                    depth[w] = depth[v] + 1
                    queue.append(w)
        rows.extend((start, a, d) for a, d in sorted(depth.items()) if d > 0)
    return rows


def rebuild_closure(neo, cur, plan: dict, dry: bool) -> dict:
    """Rebuild the closure into the SHADOW table and diff — the protocol from
    docs/rag/STRATEGY_A_CLOSURE_DESIGN.md. Never overwrites prerequisite_closure
    directly; promotion is a separate, explicit step.

    In --dry-run the graph has not been merged, so running apoc over it would
    just re-derive today's closure and report a meaningless +0/-0. The dry path
    therefore PROJECTS the post-merge closure by applying the merge map to the
    live REQUIRES edges. The apply path uses apoc against the already-merged
    graph, which is the authoritative result."""
    if dry:
        merges, deletes = plan["merges"], set(plan["deletes"])
        live = [(r["f"], r["t"]) for r in neo.run(
            "MATCH (a:Skill)-[:REQUIRES]->(b:Skill) RETURN a.name AS f, b.name AS t")]
        projected = {(merges.get(f, f), merges.get(t, t)) for f, t in live}
        projected = {(f, t) for f, t in projected
                     if f not in deletes and t not in deletes and f != t}
        rows = closure_from_edges(sorted(projected))
        skills = sorted({f for f, _ in projected})
    else:
        skills = [r["name"] for r in neo.run(
            "MATCH (s:Skill) WHERE (s)-[:REQUIRES]->() RETURN s.name AS name ORDER BY name")]
        rows = []
        for i in range(0, len(skills), 100):
            for r in neo.run(
                """UNWIND $names AS name
                   MATCH (start:Skill {name: name})
                   CALL apoc.path.spanningTree(start,
                        {relationshipFilter:'REQUIRES>', minLevel:1, maxLevel:5, limit:1000})
                   YIELD path
                   RETURN name AS descendant, last(nodes(path)).name AS ancestor,
                          length(path) AS depth""", names=skills[i:i + 100]):
                rows.append((r["descendant"], r["ancestor"], r["depth"]))
    new = {(d, a): dep for d, a, dep in rows}

    cur.execute("SELECT descendant_skill, ancestor_skill, min_depth FROM prerequisite_closure")
    old = {(d, a): m for d, a, m in cur.fetchall()}
    diff = {
        "shadow_rows": len(rows), "current_rows": len(old),
        "added": sorted(f"{d} <- {a}" for d, a in set(new) - set(old))[:20],
        "added_count": len(set(new) - set(old)),
        "removed_count": len(set(old) - set(new)),
        "removed": sorted(f"{d} <- {a}" for d, a in set(old) - set(new))[:20],
        "depth_changed": sum(1 for k in set(new) & set(old) if new[k] != old[k]),
        "skills_with_requires": len(skills),
    }
    if not dry:
        cur.execute("TRUNCATE prerequisite_closure_test")
        cur.executemany(
            "INSERT INTO prerequisite_closure_test "
            "(descendant_skill, ancestor_skill, depth, min_depth, computed_at) "
            "VALUES (%s,%s,%s,%s,NOW())",
            [(d, a, dep, dep) for d, a, dep in rows])
    return diff


def rewrite_factory_files(plan: dict, neo, dry: bool) -> dict:
    """Keep the factory's ground-truth artefacts in step with the merge.

    Without this, factory/closure/live_load.py reverts the migration: it prunes
    REQUIRES edges the edge file no longer asserts, TRUNCATEs and reloads
    problem_requirements from the stale Q-matrix file, and refuses to promote
    the closure because the live result no longer matches its ground truth."""
    merges, deletes = plan["merges"], set(plan["deletes"])
    out = {}

    new_edges: list[dict] = []
    if F_EDGES.exists():
        seen = set()
        raw = [l for l in F_EDGES.read_text().splitlines() if l.strip()]
        for line in raw:
            e = json.loads(line)
            f, t = merges.get(e["from"], e["from"]), merges.get(e["to"], e["to"])
            # A merge can collapse both endpoints onto one node (self-loop) or
            # onto an edge the file already asserts (duplicate) — drop both.
            if f in deletes or t in deletes or f == t or (f, t) in seen:
                continue
            seen.add((f, t))
            e["from"], e["to"] = f, t
            new_edges.append(e)
        out["skill_requires_edges_v1.jsonl"] = {"before": len(raw), "after": len(new_edges)}
        if not dry:
            F_EDGES.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                       for e in new_edges))

    if F_QMATRIX.exists():
        seen, new_q = set(), []
        raw = [l for l in F_QMATRIX.read_text().splitlines() if l.strip()]
        for line in raw:
            q = json.loads(line)
            skill = merges.get(q["skill_name"], q["skill_name"])
            if skill in deletes or (skill, q["template_id"]) in seen:
                continue
            seen.add((skill, q["template_id"]))
            q["skill_name"] = skill
            new_q.append(q)
        out["problem_requirements_v1.jsonl"] = {"before": len(raw), "after": len(new_q)}
        if not dry:
            F_QMATRIX.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n"
                                         for q in new_q))

    # The closure ground truth is DERIVED, so recompute it from the rewritten
    # edges rather than string-substituting it.
    if F_EDGES.exists():
        closure = [{"descendant_skill": d, "ancestor_skill": a, "min_depth": dep}
                   for d, a, dep in closure_from_edges(
                       [(e["from"], e["to"]) for e in new_edges])]
        out["prerequisite_closure_v1.jsonl"] = {
            "before": len(F_CLOSURE.read_text().splitlines()) if F_CLOSURE.exists() else 0,
            "after": len(closure)}
        if not dry:
            F_CLOSURE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                         for r in closure))
    return out


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="plan and diff only; writes nothing to either database")
    ap.add_argument("--promote-closure", action="store_true",
                    help="after a clean shadow diff, promote it into prerequisite_closure")
    ap.add_argument("--report", default=None, help="path for the JSON manifest")
    args = ap.parse_args()
    dry = args.dry_run

    import psycopg
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    started = time.time()
    report: dict = {"mode": "dry_run" if dry else "production", "source": SOURCE}

    with driver.session() as neo, psycopg.connect(DATABASE_URL, autocommit=False) as pg:
        cur = pg.cursor()

        # -- preflight ---------------------------------------------------
        if not neo.run("SHOW PROCEDURES YIELD name WHERE name='apoc.path.spanningTree' "
                       "RETURN count(*) AS n").single()["n"]:
            log("FATAL: apoc.path.spanningTree unavailable — closure rebuild impossible.")
            return 1

        plan = build_plan(neo)
        if plan["conflicts"]:
            log(f"FATAL: plan is inconsistent — {plan['conflicts']}")
            return 1
        report["plan"] = {
            "skills_before": len(plan["nodes"]),
            "merges": plan["merges"],
            "deletes": plan["deletes"],
            "groups": plan["groups"],
        }

        log(f"=== :Skill vocabulary migration ({'DRY RUN' if dry else 'APPLY'}) ===")
        log(f"skills before          : {len(plan['nodes'])}")
        by_reason = defaultdict(int)
        for l in plan["merges"]:
            by_reason[plan["reasons"].get(l, "?")] += 1
        for k, v in sorted(by_reason.items()):
            log(f"  merge {k:26}: {v}")
        log(f"  structural deletes        : {len(plan['deletes'])}")
        log(f"skills after           : {len(plan['nodes']) - len(plan['merges']) - len(plan['deletes'])}")

        # -- 1. pin BEFORE anything moves --------------------------------
        pinned = pin_mastery_keys(neo, dry)
        report["pinned"] = pinned
        log(f"\n[1] pinned :Problem.mastery_key on {pinned} problem(s) "
            f"({'would pin' if dry else 'pinned'}; coalesce makes re-runs no-ops)")

        # -- 2. key delta ------------------------------------------------
        delta = key_delta(neo, plan)
        report["key_delta"] = delta
        causes = defaultdict(int)
        for d in delta:
            causes[d["cause"]] += 1
        log(f"\n[2] mastery-key delta: {len(delta)} problem(s) would change key "
            f"WITHOUT the pin — {dict(causes)}")
        for d in delta:
            log(f"      {d['template_id']:34} {d['old_key']!r} -> {d['new_key']!r}  [{d['cause']}]")
        if any(d["cause"] == "unservable" for d in delta):
            log("FATAL: a problem would be left with no skill parent.")
            return 1
        log("    the pin absorbs all of these: attribution is frozen, so none of them move.")

        # -- 3. graph mutations ------------------------------------------
        if not dry:
            for loser, survivor in sorted(plan["merges"].items()):
                merge_skill(neo, loser, survivor)
            for name in plan["deletes"]:
                delete_structural(neo, name)
        else:
            # Run the same safety check the real delete runs, so a dry run fails
            # for exactly the reasons the real one would.
            for name in plan["deletes"]:
                delete_structural(neo, name, check_only=True)
        log(f"\n[3] graph: {'would merge' if dry else 'merged'} {len(plan['merges'])} node(s), "
            f"{'would delete' if dry else 'deleted'} {len(plan['deletes'])} structural node(s)")

        # -- 4. maintain the pin -----------------------------------------
        pins = repoint_pins(neo, plan, dry)
        report["pin_repoint"] = pins
        log(f"[4] pins re-pointed: {pins['renamed']} followed a merge, "
            f"{pins['recomputed']} recomputed after a structural delete")

        # -- 5. Postgres --------------------------------------------------
        pg_stats = migrate_pg_keys(cur, plan, dry)
        qm = repoint_qmatrix(cur, plan, dry)
        report["postgres"] = {"mastery": pg_stats, "problem_requirements": qm}
        log(f"\n[5] postgres mastery surfaces: {pg_stats or 'no rows carry an affected key'}")
        log(f"    problem_requirements: {qm}")

        # -- 6. closure into the shadow -----------------------------------
        diff = rebuild_closure(neo, cur, plan, dry)
        report["closure_diff"] = diff
        log(f"\n[6] closure shadow rebuild: {diff['shadow_rows']} rows "
            f"(was {diff['current_rows']}); +{diff['added_count']} -{diff['removed_count']} "
            f"depth-changed {diff['depth_changed']}")
        for r in diff["removed"][:8]:
            log(f"      - {r}")
        for r in diff["added"][:8]:
            log(f"      + {r}")

        # -- 7. factory artefacts -----------------------------------------
        files = rewrite_factory_files(plan, neo, dry)
        report["factory_files"] = files
        log(f"\n[7] factory ground truth (prevents live_load.py reverting the merge):")
        for name, st in files.items():
            log(f"      {name:36} {st['before']} -> {st['after']}")

        # -- 8. promote / manifest ----------------------------------------
        if not dry:
            cur.execute(
                "INSERT INTO sync_manifest (source, target_table, status, rows_written, "
                "finished_at, duration_ms) VALUES (%s,%s,%s,%s,NOW(),%s)",
                (SOURCE, "prerequisite_closure_test", "dry_run", diff["shadow_rows"],
                 int((time.time() - started) * 1000)))
            if args.promote_closure:
                cur.execute("TRUNCATE prerequisite_closure")
                cur.execute("INSERT INTO prerequisite_closure "
                            "SELECT * FROM prerequisite_closure_test")
                cur.execute(
                    "INSERT INTO sync_manifest (source, target_table, status, rows_written, "
                    "finished_at, duration_ms) VALUES (%s,%s,%s,%s,NOW(),%s)",
                    (SOURCE, "prerequisite_closure", "production", diff["shadow_rows"],
                     int((time.time() - started) * 1000)))
                log(f"[8] promoted shadow -> prerequisite_closure ({diff['shadow_rows']} rows)")
            else:
                log("[8] shadow NOT promoted (pass --promote-closure once the diff is agreed "
                    "with the RAG chat)")
            pg.commit()
        else:
            pg.rollback()

        after = neo.run("MATCH (s:Skill) RETURN count(s) AS n").single()["n"]
        report["skills_after"] = after
        log(f"\n:Skill count now {after}")

    driver.close()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    # Timestamped, never clobbering. A fixed filename loses the audit trail the
    # moment the migration is re-run: the second (idempotent, no-op) run would
    # overwrite the record of what the first run actually changed, which is
    # precisely the evidence a mastery migration has to keep.
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = Path(args.report) if args.report else REPORT_DIR / (
        f"skill_vocabulary_{'dry_run' if dry else 'applied'}_{stamp}.json")
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"manifest -> {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
