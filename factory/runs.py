#!/usr/bin/env python3
"""Factory run lanes — the RAG-owned implementations behind the two Celery stubs.

Contract (backend, 2026-09-02): `factory.nightly_run` (beat 00:00 UTC) and
`factory.hourly_run` (:15) in services/workers/worker/tasks/factory.py call these.
Until `verify_seed.py --db` is green this runs with the FILE SINK
(data/factory/runs/ + data/factory/state/); the DB/Redis sink swaps in at the
MERGE window without touching lane logic. Zero runtime consumers, batch only.

Nightly (v1 scope): T2 generation for target subtopics -> 7-stage audit ->
adapter -> zod-validated delivery records -> run report (tokens=0: no AI in T1/T2).
Hourly: pool check (<50 -> make 100) via the T1-T5 ladder — T1 resample,
T2 difficulty escalate, T3 sibling bridge (FRONTIER_OF adjacency from the graph
export), T4/T5 explicitly GATED offline (T4 needs jester models, T5 needs the
explainer store) and logged, never silently skipped.
"""

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from factory.adapters.solvealong_adapter import adapt, validate_frontend_record
from factory.audit.auditor import Auditor
from factory.generation import t2
from factory.sinks import deliver as sink_deliver

STATE_DIR = Path("data/factory/state")
RUNS_DIR = Path("data/factory/runs")
POOL_THRESHOLD = 50
POOL_REFILL = 100
MAX_AUDIT_RETRIES = 3  # master_orchestrator_config.global_thresholds

# Nightly composition (the pool composer proper arrives with BKT/seen data).
# Counts are capacity-aware per (pattern, level): the near-base patterns exhaust
# their parameter space at L1/L2 (a base-10 deviation of 2-3 admits only a handful
# of pairs), so volume is asked of the wide-space patterns instead.
DEFAULT_TARGETS = [
    # narrow spaces — ask little at low levels
    ("mult_near_base", 1, 5), ("mult_near_base", 3, 30), ("mult_near_base", 4, 30),
    ("square_near_base", 2, 15), ("square_near_base", 3, 25), ("square_near_base", 4, 25),
    ("ekadhikena_square_5", 1, 8), ("ekadhikena_square_5", 3, 25),
    ("ekadhikena_square_5", 5, 25),
    # wide spaces — carry the volume
    ("urdhva_2x2", 1, 40), ("urdhva_2x2", 2, 40), ("urdhva_2x2", 3, 40),
    ("urdhva_2x2", 4, 30), ("urdhva_2x2", 5, 30),
    ("nikhilam_complement", 1, 30), ("nikhilam_complement", 3, 30),
    ("nikhilam_complement", 5, 30),
    ("mult_by_11", 1, 25), ("mult_by_11", 3, 25),
]

PATTERN_LEVELS = {pid: [1, 2, 3, 4, 5] for pid in t2.PATTERNS}


def to_factory_shape(rec: dict) -> dict:
    """T2 record -> recovered factory-side template shape (one adapter for all lanes)."""
    return {
        "template_type": "solve_along",
        "template_id": rec["template_id"],
        "source": {"book": f"pattern:{rec['pattern_id']}"},
        "concept": {"topic": rec["topic"], "sub_topic": rec["sub_topic"],
                    "technique_name": rec["technique_name"]},
        "difficulty": rec["difficulty"],
        "cognitive_load_score": rec["cognitive_load_score"],
        "prerequisite_chain": rec["prerequisite_chain"],
        "visual_scaffold": rec["visual_scaffold"],
        "examples": [{"example_num": 1, "problem_statement": rec["problem_statement"],
                      "solution": rec["solution"], "final_answer": rec["final_answer"]}],
        "common_mistakes": rec["traps"],
        "_validation_status": None,  # trust comes from the auditor verdict, not legacy fields
    }


def _load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _bridge_map(exports=Path("incoming/topic_browser_full_package/db_exports")) -> dict:
    """Skill -> adjacent skills (FRONTIER_OF, undirected, max 1 hop) for T3 bridging."""
    adj = defaultdict(set)
    rels = exports / "relationships.jsonl"
    if rels.exists():
        for line in rels.read_text().splitlines():
            r = json.loads(line)
            if r["rel_type"] == "FRONTIER_OF":
                adj[r["start_key"]].add(r["end_key"])
    return adj


def _generate_audited(pattern_id: str, level: int, count: int, run_seed: str,
                      auditor: Auditor, stats: Counter, variance_boost: int = 0):
    """Generate + audit with resample-on-reject (max 3 rounds). Returns audited records."""
    kept, need = [], count
    for retry in range(MAX_AUDIT_RETRIES):
        batch = t2.generate(pattern_id, level, need, f"{run_seed}:r{retry}", variance_boost)
        if not batch:
            break
        for rec in batch:
            result = auditor.audit(rec)
            stats[f"audit_{result['verdict']}"] += 1
            if result["failed_stage"]:
                stats[f"fail_stage_{result['failed_stage']}"] += 1
                continue
            rec["_audit"] = result
            kept.append(rec)
        need = count - len(kept)
        if need <= 0:
            break
        stats["resample_rounds"] += 1
    return kept


def _deliver(audited: list[dict], stats: Counter):
    """Factory shape -> adapter -> zod gate. Returns delivery rows."""
    out = []
    for rec in audited:
        shaped = to_factory_shape(rec)
        delivery, _meta = adapt(shaped)
        if delivery is None or validate_frontend_record(delivery):
            stats["delivery_invalid"] += 1  # adapter/pattern bug — never ship silently
            continue
        delivery["generationMethod"] = "template"
        out.append({"delivery": delivery, "trust": rec["_audit"]["verdict"],
                    "sub_topic": rec["sub_topic"], "params_hash": rec["params_hash"]})
    return out


def _write_run(run_id: str, lane: str, rows: list[dict], stats: Counter, extra: dict):
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "delivery.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pool_path = STATE_DIR / "pool.json"
    pool = _load_json(pool_path, {})
    for r in rows:
        pool[r["sub_topic"]] = pool.get(r["sub_topic"], 0) + 1
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    pool_path.write_text(json.dumps(pool, indent=1, ensure_ascii=False))
    sink_result = sink_deliver(rows, run_id, lane)
    report = {"run_id": run_id, "lane": lane, "tokens_spent": 0,
              "delivered": len(rows), "stats": dict(stats), "sink": sink_result,
              "pool_depth_after": sink_result.get("tray_depth", pool), **extra}
    (run_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return report


def nightly_run(targets=None, run_seed: str | None = None) -> dict:
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-nightly"
    run_seed = run_seed or run_id
    auditor = Auditor(seen_store=STATE_DIR / "seen_hashes.json")
    stats: Counter = Counter()
    rows = []
    for pattern_id, level, count in (targets or DEFAULT_TARGETS):
        audited = _generate_audited(pattern_id, level, count, run_seed, auditor, stats)
        rows.extend(_deliver(audited, stats))
    auditor.persist_seen()
    return _write_run(run_id, "nightly", rows, stats,
                      {"targets": targets or DEFAULT_TARGETS})


def hourly_run(threshold: int = POOL_THRESHOLD, refill: int = POOL_REFILL) -> dict:
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-hourly"
    auditor = Auditor(seen_store=STATE_DIR / "seen_hashes.json")
    stats: Counter = Counter()
    pool = _load_json(STATE_DIR / "pool.json", {})
    bridge = _bridge_map()
    pattern_by_subtopic = {}
    for pid, fn in t2.PATTERNS.items():
        probe = t2.generate(pid, 1, 1, "probe")[0]
        pattern_by_subtopic[probe["sub_topic"]] = pid

    rows, ladder_log = [], []
    low = [(st, n) for st, n in pool.items() if n < threshold] or \
          [(st, 0) for st in pattern_by_subtopic if st not in pool]
    for sub_topic, depth in low:
        needed = refill
        pid = pattern_by_subtopic.get(sub_topic)
        # T1: resample with wider variance, stricter dedup (the shared seen store)
        if pid:
            audited = _generate_audited(pid, 2, needed, f"{run_id}:T1", auditor, stats,
                                        variance_boost=1)
            got = _deliver(audited, stats)
            rows.extend(got)
            needed -= len(got)
            ladder_log.append({"sub_topic": sub_topic, "tier": "T1", "made": len(got)})
        # T2: escalate difficulty
        if pid and needed > 0:
            audited = _generate_audited(pid, 3, needed, f"{run_id}:T2esc", auditor, stats)
            got = _deliver(audited, stats)
            rows.extend(got)
            needed -= len(got)
            ladder_log.append({"sub_topic": sub_topic, "tier": "T2_escalate", "made": len(got)})
        # T3: sibling bridge, max 1 hop
        if needed > 0:
            sibs = [s for s in bridge.get(sub_topic, ()) if s in pattern_by_subtopic]
            for sib in sibs:
                if needed <= 0:
                    break
                audited = _generate_audited(pattern_by_subtopic[sib], 2, needed,
                                            f"{run_id}:T3", auditor, stats)
                got = _deliver(audited, stats)
                rows.extend(got)
                needed -= len(got)
                ladder_log.append({"sub_topic": sub_topic, "tier": "T3_bridge",
                                   "from": sib, "made": len(got)})
        # T4/T5: gated offline — logged, never silent
        if needed > 0:
            ladder_log.append({"sub_topic": sub_topic, "tier": "T4_llm_regenerate",
                               "status": "GATED_no_jester_models", "short_by": needed})
            ladder_log.append({"sub_topic": sub_topic, "tier": "T5_explainer_conversion",
                               "status": "GATED_alert_operator", "short_by": needed})
            stats["tier45_gated_subtopics"] += 1
    auditor.persist_seen()
    return _write_run(run_id, "hourly", rows, stats,
                      {"threshold": threshold, "ladder": ladder_log})


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Factory run lanes (file-sink mode)")
    ap.add_argument("lane", choices=["nightly", "hourly"])
    args = ap.parse_args()
    report = nightly_run() if args.lane == "nightly" else hourly_run()
    print(json.dumps({k: v for k, v in report.items() if k != "pool_depth_after"}, indent=1))
    print("pool:", json.dumps(report["pool_depth_after"], indent=1))
