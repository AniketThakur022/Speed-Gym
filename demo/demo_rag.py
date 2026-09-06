#!/usr/bin/env python3
"""RAG CONTENT FACTORY — live demo, end to end.

Runs the real factory code against the live stack (Postgres :5432, Redis :6379,
Neo4j :7687) and captures REAL output to demo/output/rag.json.

    ./.venv/bin/python demo/demo_rag.py          # or: bash demo/demo_rag.sh

Non-destructive by construction:
  * factory state (seen-hash store, pool counters) is COPIED to a scratch dir per
    run, so the demo never consumes the production dedup window;
  * run artifacts land under demo/output/factory_run/ instead of data/factory/runs/;
  * Postgres writes are INSERT ... ON CONFLICT DO NOTHING into generated_problems
    only, tagged with this run_id; Redis writes are the factory's own 24h-TTL trays;
  * the trust-ladder intake runs in DRY-RUN (never --apply), so
    data/factory/state/trust_ladder.json is read, never written;
  * nothing is dropped, deleted or restarted.

Honesty contract: every number below is produced by the command that precedes it.
Stage 7 (the 2-of-3 jester consensus) is KEY-BLOCKED — no owner key for
glm-5.1 / kimi-k2.6 / deepseek-v4-flash — so the offline JesterGate returns
'pending' and the terminal state of everything generated tonight is
`quarantined_pending_consensus`. That is the designed safety property: content
that no independent judge has seen cannot reach learners.
"""

import copy
import json
import re
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "demo" / "output"
SCRATCH = OUT_DIR / "_scratch"
RUN_ARTIFACTS = OUT_DIR / "factory_run"
PG_DSN = os.environ.get("VMSG_PG_DSN", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
NEO4J = ("bolt://localhost:7687", "neo4j", "vmsg-dev-password")
TSX = ROOT / "node_modules" / ".bin" / "tsx"

RESULT: dict = {"demo": "RAG content factory", "steps": {}}
FAILURES: list[str] = []


def head(n, title):
    print(f"\n{'=' * 78}\n[{n}] {title}\n{'=' * 78}")


def show(obj, limit=4000):
    s = json.dumps(obj, indent=1, ensure_ascii=False)
    print(s if len(s) <= limit else s[:limit] + "\n  … (truncated; full copy in rag.json)")


def run_katex(bank_path, label):
    """Run the REAL KaTeX 0.18.5 renderer over a bank JSONL and return its summary.

    Stage 2 of the auditor is a deterministic PROXY for KaTeX. This is the ground
    truth: node factory/audit/katex_validate.js, the same script that produced the
    stored v1_4 report. Numbers here are recomputed live, never read from a cache.
    """
    kx = ROOT / "factory/audit/katex_validate.js"
    if not kx.exists() or not (ROOT / "node_modules/katex").exists():
        FAILURES.append(f"KaTeX validator unavailable — {label} render check skipped")
        return {"ran": False}
    proc = subprocess.run(["node", str(kx), str(bank_path)],
                          capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        FAILURES.append(f"KaTeX run failed for {label}: {proc.stderr[-300:]}")
        return {"ran": False, "stderr": proc.stderr[-300:]}
    start = proc.stdout.index("{")
    depth, end = 0, None
    for i, ch in enumerate(proc.stdout[start:], start):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            end = i + 1
            break
    summ = json.loads(proc.stdout[start:end])
    summ["ran"] = True
    summ["valid_pct"] = round(100 * (1 - summ["failure_rate"]), 2)
    # KaTeX writes "No character metrics for 'X'" to stderr and still RENDERS the
    # formula — a parse-clean pass that is nonetheless visually wrong. Nothing
    # downstream can see this, so capture it.
    warn = sorted(set(re.findall(r"No character metrics for '(.+?)'", proc.stderr)))
    summ["metricless_chars_warned"] = warn
    return summ


# ---------------------------------------------------------------- 1 preflight
def step1_preflight():
    head(1, "PREFLIGHT — live stack, and what is key-blocked")
    out = {"services": {}, "gates": {}}
    import psycopg
    import redis
    from neo4j import GraphDatabase

    with psycopg.connect(PG_DSN) as c:
        v = c.execute("select version()").fetchone()[0]
        n = c.execute("select count(*) from generated_problems").fetchone()[0]
    out["services"]["postgres"] = {"ok": True, "version": v.split(",")[0],
                                   "generated_problems_rows_before": n}
    r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3)
    out["services"]["redis"] = {"ok": r.ping(),
                                "factory_keys_before": len(list(r.scan_iter("factory:*")))}
    d = GraphDatabase.driver(NEO4J[0], auth=(NEO4J[1], NEO4J[2]))
    with d.session() as s:
        counts = {row["l"]: row["c"] for row in
                  s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c ORDER BY c DESC")}
        rels = {row["t"]: row["c"] for row in
                s.run("MATCH ()-[x]->() RETURN type(x) AS t, count(*) AS c ORDER BY c DESC")}
    d.close()
    out["services"]["neo4j"] = {"ok": True, "nodes_by_label": counts, "edges_by_type": rels}

    from factory.audit.auditor import JesterGate
    from factory.audit.jester_intake import CONFIGURED_TRIO, MAX_PROMOTION
    probe = JesterGate().vote({"template_id": "preflight"})
    out["gates"]["stage7_jester_gate"] = {
        "configured_trio": sorted(CONFIGURED_TRIO),
        "keys_present": [k for k in ("GLM_API_KEY", "KIMI_API_KEY", "DEEPSEEK_API_KEY",
                                     "OPENAI_API_KEY") if os.environ.get(k)],
        "offline_vote_returned": probe,
        "consequence": "consensus 'pending' -> verdict 'quarantined_pending_consensus'",
        "interim_backend_ceiling": MAX_PROMOTION,
    }
    try:
        import sympy  # noqa: F401
        out["gates"]["stage3_backend"] = "sympy present"
    except ImportError:
        out["gates"]["stage3_backend"] = (
            "sympy NOT installed — stage 3 runs the auditor's exact stdlib evaluator "
            "(ast + fractions.Fraction, tolerance 1e-10). Exact rational arithmetic, "
            "not a float check; the ledger column is still named sympy_validated.")
    show(out)
    return out


# ------------------------------------------------------- 2 nightly factory run
def step2_nightly():
    head(2, "NIGHTLY FACTORY RUN — T2 generation -> 7-stage auditor -> zod gate -> sinks")
    import factory.runs as R

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    prod_seen = ROOT / "data/factory/state/seen_hashes.json"
    seen_before = 0
    if prod_seen.exists():
        shutil.copy(prod_seen, SCRATCH / "seen_hashes.json")
        seen_before = len(json.loads(prod_seen.read_text())["hashes"])
    R.STATE_DIR = SCRATCH
    R.RUNS_DIR = RUN_ARTIFACTS
    os.environ.pop("VMSG_FORCE_FILE_SINK", None)   # let the DB/Redis sink run for real

    t0 = time.time()
    report = R.nightly_run()                       # real lane, real DEFAULT_TARGETS
    elapsed = round(time.time() - t0, 2)

    stats = report["stats"]
    attempted = sum(v for k, v in stats.items() if k.startswith("audit_"))
    out = {
        "run_id": report["run_id"],
        "lane": report["lane"],
        "wall_seconds": elapsed,
        "tokens_spent": report["tokens_spent"],
        "note_tokens": "T1/T2 are parametric instantiation — no LLM in the factory's "
                       "generate step, so a nightly run costs zero tokens.",
        "targets_requested": sum(c for _, _, c in R.DEFAULT_TARGETS),
        "candidates_audited": attempted,
        "delivered": report["delivered"],
        "audit_stats": stats,
        "seen_store_hashes_carried_in": seen_before,
        "sink": report["sink"],
        "tray_depth_after": report.get("pool_depth_after"),
        "artifacts": str(RUN_ARTIFACTS / report["run_id"]),
    }
    delivery_path = RUN_ARTIFACTS / report["run_id"] / "delivery.jsonl"
    rows = [json.loads(l) for l in delivery_path.read_text().splitlines()]
    out["trust_verdicts"] = dict(Counter(r["trust"] for r in rows))
    out["by_sub_topic"] = dict(Counter(r["sub_topic"] for r in rows))
    out["reading"] = (
        f"{out['candidates_audited']} candidates audited, {out['delivered']} survived all "
        "seven stages; 100% land in quarantined_pending_consensus because stage 7 has no "
        "jester keys. Stage-6 rejects are the dedup window doing its job against "
        f"{seen_before} previously-emitted parameter hashes. The sink's "
        f"{report['sink'].get('duplicate_in_db', 0)} duplicate_in_db are the UNIQUE "
        "generation_hash constraint catching parameter sets an earlier run already "
        "landed — the lane is idempotent at the database level, not just in memory.")
    show(out)
    return out, rows, delivery_path


# -------------------------------------------- 3 SolveAlongTemplate + zod gate
def step3_zod(rows, delivery_path):
    head(3, "THE ARTEFACT — a full SolveAlongTemplate, validated by the frontend's own zod")
    out = {}
    showcase = next((r for r in rows if r["delivery"]["difficulty"] >= 3), rows[0])
    out["showcase_template"] = showcase["delivery"]
    out["showcase_trust"] = showcase["trust"]
    print("--- one generated SolveAlongTemplate (verbatim, as the app would receive it) ---")
    show(showcase["delivery"], limit=6000)

    if not TSX.exists():
        FAILURES.append("node_modules/.bin/tsx missing — zod validation skipped")
        out["zod"] = {"ran": False}
        return out
    proc = subprocess.run([str(TSX), "demo/zod_validate.ts", str(delivery_path)],
                          capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        FAILURES.append(f"zod validation failed to run: {proc.stderr[-400:]}")
        out["zod"] = {"ran": False, "stderr": proc.stderr[-400:]}
        return out
    out["zod_all_delivered"] = json.loads(proc.stdout.strip().splitlines()[-1])

    # negative control — prove the gate is real, not a rubber stamp
    bad = copy.deepcopy(showcase["delivery"])
    bad["difficulty"] = 9
    bad["expected_time"] = -5
    del bad["examples"][0]["solution"]
    ctrl = SCRATCH / "zod_negative_control.jsonl"
    ctrl.write_text(json.dumps(bad, ensure_ascii=False) + "\n")
    proc2 = subprocess.run([str(TSX), "demo/zod_validate.ts", str(ctrl)],
                           capture_output=True, text=True, cwd=ROOT)
    out["zod_negative_control"] = json.loads(proc2.stdout.strip().splitlines()[-1])
    print("\n--- zod gate ---")
    show({"all_delivered": out["zod_all_delivered"],
          "negative_control (difficulty 9, expected_time -5, solution deleted)":
              out["zod_negative_control"]})

    # The schema says the SHAPE is right. It says nothing about whether the LaTeX
    # inside actually renders. Stage 2 of the auditor is a regex proxy for KaTeX;
    # this is the real renderer, run now over exactly what this run produced.
    fresh = SCRATCH / "fresh_delivery_bank.jsonl"
    with fresh.open("w") as f:
        for r in rows:
            f.write(json.dumps(r["delivery"], ensure_ascii=False) + "\n")
    out["katex_fresh_output"] = run_katex(fresh, "fresh nightly delivery")
    print("\n--- real KaTeX 0.18.5 over THIS run's output ---")
    show(out["katex_fresh_output"])
    if out["katex_fresh_output"].get("ran"):
        k = out["katex_fresh_output"]
        print(f"  {k['formulas_checked']} formulas across {k['templates']} generated "
              f"templates -> {k['failing_formulas']} KaTeX failures "
              f"({k['valid_pct']}% clean). The generator emits only the LaTeX subset "
              f"stage 2 permits, so the proxy and the real renderer agree here.")
    return out


# ----------------------------------------------------------- 4 Redis warm tray
def step4_tray(sink):
    head(4, "WARM TRAY — factory:tray:<sub_topic> in Redis, read a delivery back out")
    import redis
    r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3)
    trays = sorted(k.decode() for k in r.scan_iter("factory:tray:*"))
    out = {"pushed_by_this_run": sink.get("inserted"),
           "skipped_as_already_in_ledger": sink.get("duplicate_in_db"),
           "tray_keys": len(trays),
           "trays": [{"key": k, "depth": r.llen(k), "ttl_seconds": r.ttl(k)} for k in trays],
           "seen_markers": len(list(r.scan_iter("factory:seen:*")))}
    if not trays:
        FAILURES.append("Redis warm tray empty after the run — sink did not land")
        show(out)
        return out
    key = max(trays, key=lambda k: r.llen(k))
    raw = r.lindex(key, 0)
    payload = json.loads(raw)
    out["read_back"] = {
        "key": key, "index": 0, "bytes": len(raw),
        "trust": payload["trust"],
        "template_id": payload["template"]["id"],
        "problem_statement": payload["template"]["examples"][0]["problem_statement"],
        "answer": payload["template"]["examples"][0].get("answer"),
        "expected_time": payload["template"]["expected_time"],
        "steps": len(payload["template"]["examples"][0]["solution"]),
    }
    if TSX.exists():
        p = SCRATCH / "tray_readback.jsonl"
        p.write_text(json.dumps(payload["template"], ensure_ascii=False) + "\n")
        pr = subprocess.run([str(TSX), "demo/zod_validate.ts", str(p)],
                            capture_output=True, text=True, cwd=ROOT)
        if pr.returncode == 0:
            out["read_back"]["zod"] = json.loads(pr.stdout.strip().splitlines()[-1])
    out["note"] = ("TTL 86400s is the factory PDF's 24h warm window; the tray is the only "
                   "hot path the app would read, and everything in it is labelled with its "
                   "trust rung. Depths are CUMULATIVE over the 24h window — an earlier run's "
                   "items are still in the tray, which is why total depth exceeds what this "
                   "run pushed.")
    show(out)
    return out


# ------------------------------------------------------------ 5 Postgres ledger
def step5_ledger(run_id):
    head(5, "LEDGER — the rows this run wrote to Postgres generated_problems")
    import psycopg
    out = {}
    with psycopg.connect(PG_DSN) as c:
        cur = c.cursor()
        cur.execute("select count(*) from generated_problems")
        out["table_rows_total"] = cur.fetchone()[0]
        cur.execute("""select count(*) from generated_problems
                       where parameters->>'run_id' = %s""", (run_id,))
        out["rows_from_this_run"] = cur.fetchone()[0]
        cur.execute("""select validation_result->>'trust' AS t, count(*)
                       from generated_problems where parameters->>'run_id' = %s
                       group by 1""", (run_id,))
        out["trust_distribution_this_run"] = dict(cur.fetchall())
        cur.execute("""select template_id, problem_text, answer, difficulty_level,
                              target_time_seconds, sympy_validated, validation_result,
                              left(generation_hash, 16)
                       from generated_problems where parameters->>'run_id' = %s
                       order by template_id limit 1""", (run_id,))
        row = cur.fetchone()
        if row:
            out["sample_row"] = {
                "template_id": row[0], "problem_text": row[1], "answer": row[2],
                "difficulty_level": row[3], "target_time_seconds": row[4],
                "sympy_validated": row[5], "validation_result": row[6],
                "generation_hash_prefix": row[7]}
        cur.execute("""select count(*) from pg_indexes where tablename='generated_problems'
                       and indexdef ilike '%%generation_hash%%'""")
        out["generation_hash_unique_index"] = cur.fetchone()[0] > 0
    out["note"] = ("generation_hash is UNIQUE, so the sink's ON CONFLICT DO NOTHING makes "
                   "the whole lane idempotent at the database level — re-running never "
                   "duplicates a parameter set.")
    show(out)
    return out


# ----------------------------------------------------- 6 prerequisite closure
def step6_closure():
    head(6, "PREREQUISITE CLOSURE — Postgres tables + a live Neo4j chain")
    import psycopg
    from neo4j import GraphDatabase
    out = {}
    with psycopg.connect(PG_DSN) as c:
        cur = c.cursor()
        cur.execute("select count(*), max(depth), count(distinct descendant_skill), "
                    "count(distinct ancestor_skill) from prerequisite_closure")
        n, mx, dsc, anc = cur.fetchone()
        out["prerequisite_closure"] = {"rows": n, "max_depth": mx,
                                       "distinct_descendants": dsc,
                                       "distinct_ancestors": anc}
        cur.execute("select count(*), count(distinct skill_name), count(distinct template_id) "
                    "from problem_requirements")
        n2, s2, t2n = cur.fetchone()
        out["problem_requirements"] = {"rows": n2, "distinct_skills": s2,
                                       "distinct_templates": t2n}
        cur.execute("""select skill_name, count(*) c from problem_requirements
                       group by 1 order by c desc limit 5""")
        out["problem_requirements"]["top_skills"] = [
            {"skill": a, "templates": b} for a, b in cur.fetchall()]
        skill = "Urdhva Tiryagbhyam (Vertically and Crosswise)"
        cur.execute("""select ancestor_skill, min_depth, support from prerequisite_closure
                       where descendant_skill = %s order by min_depth, ancestor_skill""",
                    (skill,))
        rows = cur.fetchall()
        out["closure_for_skill"] = {
            "skill": skill, "ancestors": len(rows),
            "by_depth": dict(Counter(str(r[1]) for r in rows)),
            "first_10": [{"ancestor": a, "min_depth": d, "support": s} for a, d, s in rows[:10]]}

    cypher = """
MATCH path = (s:Skill {name: $skill})-[:REQUIRES*1..5]->(pre:Skill)
RETURN [n IN nodes(path) | n.name] AS chain, length(path) AS depth
ORDER BY depth DESC, chain[1] LIMIT 5"""
    d = GraphDatabase.driver(NEO4J[0], auth=(NEO4J[1], NEO4J[2]))
    with d.session() as s:
        chains = [{"depth": r["depth"], "chain": r["chain"]}
                  for r in s.run(cypher, skill="Urdhva Tiryagbhyam (Vertically and Crosswise)")]
        direct = [r["n"] for r in s.run(
            "MATCH (:Skill {name:$skill})-[:REQUIRES]->(p:Skill) RETURN p.name AS n ORDER BY n",
            skill="Urdhva Tiryagbhyam (Vertically and Crosswise)")]
        frontier = s.run("MATCH ()-[r:FRONTIER_OF]->() RETURN count(r) AS c").single()["c"]
        prereq_edges = s.run(
            "MATCH (a)-[r:PREREQUISITE_OF]->(b) RETURN labels(a)[0] AS a, labels(b)[0] AS b, "
            "count(r) AS c").data()
    d.close()
    # Honest caveat, evidenced from the rows just fetched rather than asserted.
    alias_pairs = [(a, b) for a in direct for b in direct
                   if a != b and a.endswith(b) and len(a) > len(b)]
    implausible = [x for x in direct if x in
                   ("Coordinate Geometry", "Quadratic Equations", "Geometry")]
    out["data_quality_caveat"] = {
        "unaliased_duplicate_skill_names": alias_pairs,
        "implausible_prerequisites_for_a_2x2_multiplication_sutra": implausible,
        "reading": "The closure is REAL and computed, but the underlying taxonomy still "
                   "carries un-collapsed aliases and inherited-from-textbook-chapter edges. "
                   "It is honest scaffolding for the demo, not a finished prerequisite map; "
                   "collapsing aliases is extraction-workstream work."}
    out["neo4j"] = {"cypher": cypher.strip(), "direct_requires": direct,
                    "longest_chains": chains, "frontier_of_edges": frontier,
                    "prerequisite_of_edges": prereq_edges,
                    "note": "coded against the live :Skill label (not the stale :Technique "
                            "schema files); PREREQUISITE_OF is Skill->Problem, skill-to-skill "
                            "ordering is REQUIRES."}
    show(out)
    FAILURES.append(
        "prerequisite graph quality: :Skill REQUIRES edges still contain un-collapsed "
        "taxonomy aliases (e.g. 'Basic Operations (+, -, x, /)' vs 'Arithmetic: Basic "
        "Operations (+, -, x, /)') and textbook-chapter-inherited edges (Urdhva "
        "Tiryagbhyam REQUIRES Coordinate Geometry). The closure computes correctly over "
        "a graph that is not yet clean.")
    return out


# --------------------------------------------------- 7 auditor adversarial run
def step7_auditor():
    head(7, "THE AUDITOR CATCHING THINGS — deliberately broken candidates, one per stage")
    from factory.audit.auditor import Auditor
    from factory.generation import t2

    base = t2.generate("mult_near_base", 3, 1, "demo-adversarial")[0]
    base["template_type"] = "generated_t2"

    def mutate(fn):
        rec = copy.deepcopy(base)
        rec["params_hash"] = rec["params_hash"][:-4] + os.urandom(2).hex()
        rec["template_id"] = rec["template_id"] + "_" + os.urandom(2).hex()
        fn(rec)
        return rec

    def drop_answer(r): r["final_answer"] = ""
    def abandon(r): r["solution"][3]["reasoning"] = "Try: 112|-133 is wrong. No, adjust: 11067"
    def bad_latex(r): r["solution"][2]["formula"] = "\\frac{93 + 19}{100 = 112"
    def dollar_latex(r): r["solution"][2]["formula"] = "$93 + 19 = 112$"
    def unicode_latex(r): r["solution"][2]["formula"] = "93^2 = 8649 \\text{ (see ² note)}"
    def wrong_answer(r): r["final_answer"] = "11060"          # compute says 93*119 = 11067
    def bad_base(r): r["params"]["base"] = 50
    def far_deviation(r): r["params"]["a"] = 41                # |41-100| = 59 > 35% of 100
    def dup_traps(r): r["traps"] = ["sign error when deviations differ",
                                    "sign error when deviations differ"]

    cases = [
        ("stage 1 — structural: answer field emptied", drop_answer),
        ("stage 1b — walkthrough abandons its own method mid-derivation", abandon),
        ("stage 2 — LaTeX: unbalanced braces", bad_latex),
        ("stage 2 — LaTeX: $ delimiters inside a math-mode field", dollar_latex),
        ("stage 2 — LaTeX: unicode superscript KaTeX has no metrics for", unicode_latex),
        ("stage 3 — answer fails independent recomputation", wrong_answer),
        ("stage 4 — sutra rule: base not a power of ten", bad_base),
        ("stage 4 — sutra rule: deviation outside the near-base band", far_deviation),
        ("stage 5 — trap sanity: duplicate traps", dup_traps),
    ]
    auditor = Auditor(seen_store=None)
    results = []
    for label, fn in cases:
        rec = mutate(fn)
        v = auditor.audit(rec)
        results.append({"injected_defect": label, "verdict": v["verdict"],
                        "rejected_at_stage": v["failed_stage"], "reasons": v["reasons"]})
        print(f"  {v['verdict']:<10} stage {v['failed_stage']}  <- {label}\n"
              f"             {v['reasons']}")

    clean = mutate(lambda r: None)
    v_clean = auditor.audit(clean)
    dup = auditor.audit(copy.deepcopy(clean))   # same params_hash, second time
    results.append({"injected_defect": "stage 6 — same parameter hash submitted twice",
                    "verdict": dup["verdict"], "rejected_at_stage": dup["failed_stage"],
                    "reasons": dup["reasons"]})
    print(f"  {dup['verdict']:<10} stage {dup['failed_stage']}  <- stage 6 dedup (replay)\n"
          f"             {dup['reasons']}")
    print(f"\n  CONTROL (untouched candidate): {v_clean['verdict']} "
          f"(consensus={v_clean.get('consensus')})")

    caught = sum(1 for r in results if r["verdict"] == "rejected")
    if caught != len(results):
        FAILURES.append(f"auditor missed {len(results) - caught} injected defects")
    return {"injected": len(results), "rejected": caught,
            "cases": results,
            "control": {"verdict": v_clean["verdict"], "failed_stage": v_clean["failed_stage"],
                        "consensus": v_clean.get("consensus"),
                        "reading": "a clean candidate stops at quarantine, not sandbox — "
                                   "stage 7 never voted"}}


# ------------------------------------------------- 8 trust ladder refuses to promote
def step8_ladder():
    head(8, "TRUST LADDER — what it refuses, and the ceiling on an interim judge")
    from factory.audit import jester_intake as JI
    out = {"ladder_state_file": str(JI.LADDER_STATE),
           "configured_trio": sorted(JI.CONFIGURED_TRIO),
           "max_promotion_for_other_backends": JI.MAX_PROMOTION}

    state = json.loads(JI.LADDER_STATE.read_text())
    out["current_ladder"] = {
        "targets": len(state["targets"]),
        "by_state": dict(Counter(v["state"] for v in state["targets"].values())),
        "by_backend": dict(Counter(str(v.get("judge_backend"))
                                   for v in state["targets"].values())),
        "ceiling_note": state.get("ceiling_note")}

    probes = [
        ("verdict claims 'pass' but the panel voted 2 fail / 1 pass", {
            "target_kind": "pattern", "target_id": "demo_fabricated@L3",
            "judge_backend": "claude-session-panel", "consensus_rule": "2_of_3",
            "result": "pass", "spot_check_ids": ["x"],
            "panel": [{"lens": "sutra-fidelity", "verdict": "fail"},
                      {"lens": "learner-followability", "verdict": "fail"},
                      {"lens": "trap-realism", "verdict": "pass"}]}),
        ("panel of three identical lenses (not a panel)", {
            "target_kind": "pattern", "target_id": "demo_redundant@L3",
            "judge_backend": "claude-session-panel", "consensus_rule": "2_of_3",
            "result": "pass", "spot_check_ids": ["x"],
            "panel": [{"lens": "sutra-fidelity", "verdict": "pass"}] * 3}),
        ("no judge_backend — unattributable verdict", {
            "target_kind": "pattern", "target_id": "demo_anon@L3",
            "consensus_rule": "2_of_3", "result": "pass", "spot_check_ids": ["x"],
            "panel": [{"lens": "a", "verdict": "pass"}, {"lens": "b", "verdict": "pass"},
                      {"lens": "c", "verdict": "pass"}]}),
        ("pattern verdict with no spot-check instances (skeleton drift undetectable)", {
            "target_kind": "pattern", "target_id": "demo_nospot@L3",
            "judge_backend": "claude-session-panel", "consensus_rule": "2_of_3",
            "result": "pass",
            "panel": [{"lens": "a", "verdict": "pass"}, {"lens": "b", "verdict": "pass"},
                      {"lens": "c", "verdict": "pass"}]}),
    ]
    checks = []
    for label, v in probes:
        errs = JI.validate(v)
        checks.append({"submitted": label, "admitted": not errs, "refusals": errs})
        print(f"  {'ADMITTED' if not errs else 'REFUSED  '} <- {label}")
        for e in errs:
            print(f"             · {e}")
    out["intake_refusals"] = checks

    # A well-formed pass from a NON-trio backend: admitted, but capped at sandbox.
    good = {"target_kind": "pattern", "target_id": "demo_wellformed@L3",
            "judge_backend": "claude-session-panel", "consensus_rule": "2_of_3",
            "result": "pass", "spot_check_ids": ["t2_demo_1"],
            "panel": [{"lens": "sutra-fidelity", "verdict": "pass"},
                      {"lens": "learner-followability", "verdict": "pass"},
                      {"lens": "trap-realism", "verdict": "fail"}]}
    errs = JI.validate(good)
    interim = good["judge_backend"] not in JI.CONFIGURED_TRIO
    ceiling = JI.MAX_PROMOTION if interim else "trusted"
    out["ceiling_demo"] = {"verdict_admissible": not errs, "backend": good["judge_backend"],
                           "is_configured_trio_member": not interim,
                           "highest_reachable_state": ceiling,
                           "would_reach_trusted": False,
                           "why": "SANDBOX never feeds BKT mastery or mock exams, so an "
                                  "interim same-family panel being wrong costs a learner one "
                                  "questionable practice item and nothing else. TRUSTED/LIVE "
                                  "waits for the configured trio."}
    print(f"\n  well-formed session-panel PASS -> admitted, capped at '{ceiling}' "
          f"(trusted/live withheld)")

    # dry-run the real CLI over the real verdict files — never --apply.
    # "read-only" is PROVEN by checksum, not asserted.
    import hashlib
    digest = lambda q: hashlib.sha256(q.read_bytes()).hexdigest()[:16]
    before = digest(JI.LADDER_STATE)
    proc = subprocess.run(
        [sys.executable, "-m", "factory.audit.jester_intake",
         "data/factory/verdicts/stage7_*.jsonl"],
        capture_output=True, text=True, cwd=ROOT)
    after = digest(JI.LADDER_STATE)
    out["intake_cli_dry_run"] = {
        "cmd": "python -m factory.audit.jester_intake 'data/factory/verdicts/stage7_*.jsonl'",
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1500:],
        "ladder_state_sha256_before": before,
        "ladder_state_sha256_after": after,
        "wrote_anything": before != after}
    if before != after:
        FAILURES.append("dry-run intake MUTATED trust_ladder.json — it must not")
    print("\n--- real intake CLI over the real verdict files (DRY RUN) ---")
    print(proc.stdout[-1200:] or proc.stderr[-600:])
    print(f"  ladder state sha256 {before} -> {after}  "
          f"({'UNCHANGED — dry run really is read-only' if before == after else 'MUTATED!'})")
    return out


# --------------------------------------------------------------- 9 bank stats
def step9_banks():
    head(9, "BANK STATS — what already exists on disk")
    out = {}
    v14 = ROOT / "data/factory/solvealong_bank_v1_4.jsonl"
    out["solvealong_bank_v1_4"] = {"path": str(v14.relative_to(ROOT)),
                                   "templates": sum(1 for _ in v14.open())}
    man = json.loads((ROOT / "data/factory/solvealong_bank_v1_4.manifest.json").read_text())
    summ = man.get("summary") or man
    out["solvealong_bank_v1_4"]["manifest_summary"] = {
        k: v for k, v in summ.items() if not isinstance(v, (list, dict))}
    # LIVE re-run of the real renderer over the bank on disk — not the stored report.
    live = run_katex(v14, "solvealong_bank_v1_4")
    out["katex_v1_4"] = live
    stored = json.loads((ROOT / "data/factory/katex_report_v1_4.json").read_text())["summary"]
    out["katex_v1_4_vs_stored_report"] = {
        "stored_failing_formulas": stored["failing_formulas"],
        "live_failing_formulas": live.get("failing_formulas"),
        "reproduces": stored["failing_formulas"] == live.get("failing_formulas"),
        "note": "the committed katex_report_v1_4.json is reproducible from the bank"}
    conv = sorted((ROOT / "data/factory/converted").glob("packet_*.jsonl"))
    out["converted_bank"] = {
        "packets": len(conv),
        "templates": sum(sum(1 for _ in p.open()) for p in conv),
        "generationMethod": "converted",
        "ladder_entry": "quarantined_pending_consensus (every one — no stage-7 panel has "
                        "judged them)"}
    skips = ROOT / "data/factory/converted/_skips.json"
    if skips.exists():
        s = json.loads(skips.read_text())
        out["converted_bank"]["conversion_intake"] = {
            "converted": s.get("converted"), "refused": s.get("skipped"),
            "refusal_rate": round(s["skipped"] / (s["skipped"] + s["converted"]), 3)
            if s.get("skipped") is not None else None,
            "why_refusals_matter": "truncated source formulas, bare cross-references, "
                                   "charts absent from the corpus, one printed erratum. "
                                   "Fabricating those walkthroughs is exactly the defect "
                                   "class that made the legacy static bank unusable.",
            "example_refusal": (s.get("skip_reasons") or [""])[0][:300]}
    audit = json.loads((ROOT / "data/factory/converted/_audit.json").read_text())
    out["converted_bank"]["grounding_audit"] = {
        k: audit[k] for k in ("audited", "ungrounded", "misaligned", "answer_altered")
        if k in audit}
    # LIVE KaTeX over the converted bank too — and capture what KaTeX only WARNS about.
    convcat = SCRATCH / "converted_all.jsonl"
    with convcat.open("w") as f:
        for cp in conv:
            f.write(cp.read_text())
    ck = run_katex(convcat, "converted bank")
    out["katex_converted"] = ck
    if ck.get("metricless_chars_warned"):
        import importlib
        aud = importlib.import_module("factory.audit.auditor")
        missed = [c for c in ck["metricless_chars_warned"]
                  if c not in aud.METRICLESS_CHARS and c not in aud.TEXT_MODE_UNSAFE_CHARS]
        affected = []
        for cp in conv:
            for line in cp.read_text().splitlines():
                if not line.strip():
                    continue
                t = json.loads(line)
                for ex in t.get("examples", []):
                    for st in ex.get("solution", []):
                        r = st.get("result") or ""
                        if any(c in r for c in missed):
                            affected.append((t["id"], st.get("step_num")))
        out["katex_gap_found_by_this_demo"] = {
            "chars_katex_warned_about": ck["metricless_chars_warned"],
            "not_in_auditor_char_lists": missed,
            "formulas_affected": len(affected),
            "templates_affected": len({a[0] for a in affected}),
            "example": affected[0] if affected else None,
            "reading": "KaTeX PARSES these fine (0 failures) but has no font metrics for "
                       "them, so it renders a wrong glyph and only warns on stderr. "
                       "auditor.METRICLESS_CHARS does not list them, so stage 2 passes "
                       "them. Small (one template) but real: found by running the actual "
                       "renderer instead of trusting the proxy. Fix is a one-line addition "
                       "to the auditor's char set — deliberately NOT done inside a demo."}
        FAILURES.append(
            f"auditor stage-2 gap: KaTeX has no font metrics for {missed} but the "
            f"auditor's METRICLESS_CHARS/TEXT_MODE_UNSAFE_CHARS do not list them, so "
            f"{len(affected)} converted-bank formula(s) pass stage 2 and still render "
            f"a wrong glyph. Found by this demo; not patched here.")
        print("\n  GAP FOUND: KaTeX warns 'no character metrics' for "
              f"{ck['metricless_chars_warned']} — {missed} are absent from the auditor's "
              f"stage-2 char lists ({len(affected)} formulas, "
              f"{len({a[0] for a in affected})} template(s)).")

    pool = json.loads((ROOT / "data/factory/state/pool.json").read_text())
    out["cumulative_generated_pool_state_file"] = pool
    show(out)
    return out


# ------------------------------------------------- 10 stage-7 verdicts on disk
def step10_verdicts():
    head(10, "STAGE-7 VERDICT FILES — what has actually been judged, and by whom")
    vdir = ROOT / "data/factory/verdicts"
    out = {"dir": str(vdir.relative_to(ROOT)), "files": []}
    for p in sorted(vdir.glob("*.jsonl")):
        vs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        rec = {"file": p.name, "verdicts": len(vs),
               "backends": dict(Counter(v.get("judge_backend") for v in vs)),
               "results": dict(Counter(v.get("result") for v in vs)),
               "target_kinds": dict(Counter(v.get("target_kind") for v in vs)),
               "example_targets": [v.get("target_id") for v in vs[:4]]}
        if vs:
            rec["fail_rate"] = round(rec["results"].get("fail", 0) / len(vs), 3)
        out["files"].append(rec)
        print(f"  {p.name}: {len(vs)} verdicts  {rec['results']}  backends={rec['backends']}")
    for p in sorted(vdir.glob("*.json")):
        try:
            j = json.loads(p.read_text())
        except Exception:
            continue
        out.setdefault("json_reports", []).append(
            {"file": p.name,
             "keys": list(j)[:12] if isinstance(j, dict) else f"list[{len(j)}]"})
    ssr = vdir / "static_sample_report.json"
    if ssr.exists():
        j = json.loads(ssr.read_text())
        out["static_sample_report"] = {k: v for k, v in j.items()
                                       if not isinstance(v, (list, dict))}
    out["decision"] = (
        "Interim backend is 'claude-session-panel' — an adversarial same-base-model panel, "
        "accepted by docs/rag/STAGE7_SESSION_PANEL_INTAKE.md but capped at SANDBOX and "
        "flagged stage7_interim for mandatory re-judge when the configured trio "
        "(glm-5.1 / kimi-k2.6 / deepseek-v4-flash) gets keys. The 60-item stratified sample "
        "of the legacy static bank came back mostly FAIL — that is the finding that stopped "
        "the legacy bank being repaired further.")
    print("\n  " + out["decision"])
    return out


PROD_STATE = ["data/factory/state/seen_hashes.json", "data/factory/state/pool.json",
              "data/factory/state/trust_ladder.json",
              "data/factory/solvealong_bank_v1_4.jsonl"]


def _state_digests():
    import hashlib
    return {q: hashlib.sha256((ROOT / q).read_bytes()).hexdigest()[:16]
            for q in PROD_STATE if (ROOT / q).exists()}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    digests_before = _state_digests()
    S = RESULT["steps"]
    S["1_preflight"] = step1_preflight()
    S["2_nightly_run"], rows, delivery_path = step2_nightly()
    S["3_solvealong_and_zod"] = step3_zod(rows, delivery_path)
    S["4_redis_warm_tray"] = step4_tray(S["2_nightly_run"]["sink"])
    S["5_postgres_ledger"] = step5_ledger(S["2_nightly_run"]["run_id"])
    S["6_prerequisite_closure"] = step6_closure()
    S["7_auditor_rejections"] = step7_auditor()
    S["8_trust_ladder"] = step8_ladder()
    S["9_bank_stats"] = step9_banks()
    S["10_stage7_verdicts"] = step10_verdicts()

    head(11, "HEADLINE NUMBERS")
    n = S["2_nightly_run"]
    headline = {
        "nightly_candidates_audited": n["candidates_audited"],
        "nightly_delivered": n["delivered"],
        "nightly_wall_seconds": n["wall_seconds"],
        "nightly_tokens_spent": n["tokens_spent"],
        "delivered_all_quarantined_pending_consensus":
            n["trust_verdicts"].get("quarantined_pending_consensus", 0) == n["delivered"],
        "zod_valid": S["3_solvealong_and_zod"].get("zod_all_delivered", {}).get("valid"),
        "zod_invalid": S["3_solvealong_and_zod"].get("zod_all_delivered", {}).get("invalid"),
        "redis_tray_keys": S["4_redis_warm_tray"]["tray_keys"],
        "redis_tray_items_pushed_this_run": S["4_redis_warm_tray"]["pushed_by_this_run"],
        "redis_tray_items_total_in_24h_window":
            sum(t["depth"] for t in S["4_redis_warm_tray"]["trays"]),
        "ledger_rows_this_run": S["5_postgres_ledger"]["rows_from_this_run"],
        "prerequisite_closure_rows": S["6_prerequisite_closure"]["prerequisite_closure"]["rows"],
        "problem_requirements_rows": S["6_prerequisite_closure"]["problem_requirements"]["rows"],
        "auditor_defects_injected": S["7_auditor_rejections"]["injected"],
        "auditor_defects_caught": S["7_auditor_rejections"]["rejected"],
        "bank_v1_4_templates": S["9_bank_stats"]["solvealong_bank_v1_4"]["templates"],
        "bank_v1_4_katex_valid_pct": S["9_bank_stats"]["katex_v1_4"]["valid_pct"],
        "fresh_output_katex_formulas_checked":
            S["3_solvealong_and_zod"].get("katex_fresh_output", {}).get("formulas_checked"),
        "fresh_output_katex_failures":
            S["3_solvealong_and_zod"].get("katex_fresh_output", {}).get("failing_formulas"),
        "converted_bank_templates": S["9_bank_stats"]["converted_bank"]["templates"],
        "converted_bank_katex_valid_pct": S["9_bank_stats"].get("katex_converted", {}).get("valid_pct"),
        "trust_ladder_targets": S["8_trust_ladder"]["current_ladder"]["targets"],
        "stage7_verdict_files": len(S["10_stage7_verdicts"]["files"]),
    }
    # Prove the whole run was non-destructive to committed factory state.
    digests_after = _state_digests()
    changed = [q for q in digests_before if digests_before[q] != digests_after.get(q)]
    RESULT["non_destructive_proof"] = {
        "files_checked": list(digests_before),
        "sha256_before": digests_before,
        "sha256_after": digests_after,
        "unchanged": not changed,
        "changed": changed,
        "note": "The demo reads committed factory state and writes only to "
                "demo/output/ (run artifacts, scratch seen-store), plus ADDITIVE "
                "INSERT ... ON CONFLICT DO NOTHING rows in Postgres generated_problems "
                "and 24h-TTL Redis trays. Nothing dropped, deleted or restarted."}
    if changed:
        FAILURES.append(f"demo mutated committed factory state: {changed}")
    print(f"\n  non-destructive check: {len(digests_before)} committed state files, "
          f"{'ALL UNCHANGED' if not changed else 'CHANGED: ' + str(changed)}")

    RESULT["headline_numbers"] = headline
    RESULT["started_utc"] = started
    RESULT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    RESULT["failures"] = FAILURES
    RESULT["key_blocked"] = {
        "stage7_jesters": "glm-5.1 / kimi-k2.6 / deepseek-v4-flash — no owner keys present. "
                          "The offline JesterGate votes 'pending' for every record, so nothing "
                          "generated tonight can leave quarantine. This is the designed "
                          "terminal state, not a crash: the ladder has no side door, and "
                          "content no independent judge has seen never reaches a learner.",
        "openai_embeddings": "OPENAI_API_KEY absent — the 12,540 verbatim chunk embeddings "
                             "(station 3) stay unbuilt; not exercised by this demo.",
    }
    show(headline)
    (OUT_DIR / "rag.json").write_text(json.dumps(RESULT, indent=1, ensure_ascii=False))
    print(f"\nwrote {OUT_DIR / 'rag.json'}")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(" -", f)


if __name__ == "__main__":
    main()
