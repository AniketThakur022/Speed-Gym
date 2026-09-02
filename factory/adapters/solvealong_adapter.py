#!/usr/bin/env python3
"""SolveAlong bank adapter — factory-side templates -> frontend SolveAlongTemplate schema.

First real factory component (RAG workstream). Deterministic, no AI, stdlib only.

Input : recovered solve_along JSONLs (factory-side shape, 915 records / 861 unique)
Output: delivery bank JSONL (every record passes the frontend zod contract, mirrored
        here in validate_frontend_record) + a manifest with per-template trust-ladder
        entry recommendations, repairs, quarantine reasons, and provenance.

Contract: docs/rag/SOLVEALONG_CONFORMANCE_REPORT.md and the `solvealong-adapter-contract`
memory. The zod source of truth is recovered/exam-arena-src/src_lib_types_template.ts_cf55.

Trust semantics (ladder ENTRY recommendations only — actual promotion happens when the
7-stage auditor runs; nothing here bypasses the ladder):
  - excluded (quarantined): structural defects, or legacy `_validation_status: flagged`
  - sandbox_candidate: unenriched records, placeholder scaffolds, or repaired fields
  - trusted_candidate: legacy verified_L1/L2, real scaffold, mapping-only transforms
The legacy `_python_audit_status` (ALL_FAILED on 806/807) is the known-broken pre-loss
SymPy verifier (63.7% false-positive rate) and is IGNORED for trust decisions.

expected_time synthesis (age-neutral 18-25 baseline; client applies age/persona
multipliers — decision-engine spec §1.4/§5.4):
  D = 1 + 0.5*(difficulty-1)            # anchor: 30s at L1 (DE spec base)
  L = 1 + 0.15*(cognitive_load-2)       # load observed 1..7
  S = min(1.5, 1 + 0.05*max(0, median_steps-4))
  expected_time = clamp(15, round5(30*D*L*S), 300)
  # cross-anchor: L5/load3/8-step -> 125s ~= renderer spec's 120s exam target
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

SCAFFOLD_TYPES = {
    "arrow_matrix", "place_value_chart", "number_line", "grid_construction",
    "equation_chain", "shape_canvas", "coordinate_grid", "textual_scaffold",
    "rotation_diagram", "formula_generalization", "venn_diagram",
}

# All Phase-1 (Speed Gym) books ship under the vedic-math pillar; CAT/GMAT/GRE
# banks get their own rows when those lanes come online.
BOOK_DOMAIN = {
    "Tirthaji_Vedic_Math": "vedic-math",
    "Vedic_Made_Easy": "vedic-math",
    "Vedic_Secrets": "vedic-math",
    "Bird_Engineering_Math": "vedic-math",
    "Schaums_College_Math": "vedic-math",
    "Number_Sense": "vedic-math",
}
DEFAULT_DOMAIN = "vedic-math"

EXPECTED_TIME_VERSION = "et-v1"


def synth_expected_time(difficulty: int, cognitive_load: int, step_counts: list[int]) -> int:
    d = max(1, min(5, difficulty))
    cl = max(1, min(7, cognitive_load))
    med_steps = statistics.median(step_counts) if step_counts else 4
    D = 1 + 0.5 * (d - 1)
    L = 1 + 0.15 * (cl - 2)
    S = min(1.5, 1 + 0.05 * max(0, med_steps - 4))
    raw = 30 * D * L * S
    return int(max(15, min(300, 5 * round(raw / 5))))


def validate_frontend_record(r: dict) -> list[str]:
    """Strict mirror of SolveAlongTemplateSchema (zod). Returns a list of violations."""
    errs = []
    if not (isinstance(r.get("id"), str) and r["id"]):
        errs.append("id")
    if not (isinstance(r.get("domain"), str) and r["domain"]):
        errs.append("domain")
    c = r.get("concept") or {}
    if not (isinstance(c.get("technique_name"), str) and c["technique_name"]):
        errs.append("concept.technique_name")
    if not (isinstance(c.get("category"), str) and c["category"]):
        errs.append("concept.category")
    if "sub_category" in c and not isinstance(c["sub_category"], str):
        errs.append("concept.sub_category")
    d = r.get("difficulty")
    if not (isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 5):
        errs.append("difficulty")
    et = r.get("expected_time")
    if not (isinstance(et, int) and not isinstance(et, bool) and et > 0):
        errs.append("expected_time")
    vs = r.get("visual_scaffold") or {}
    if not (isinstance(vs.get("type"), str) and vs["type"]):
        errs.append("visual_scaffold.type")
    ex = r.get("examples")
    if not (isinstance(ex, list) and len(ex) >= 1):
        errs.append("examples")
    else:
        for i, e in enumerate(ex):
            if not (isinstance(e.get("problem_statement"), str) and e["problem_statement"]):
                errs.append(f"examples[{i}].problem_statement")
            if "answer" in e and not isinstance(e["answer"], str):
                errs.append(f"examples[{i}].answer")
            sol = e.get("solution")
            if not (isinstance(sol, list) and len(sol) >= 1):
                errs.append(f"examples[{i}].solution")
                continue
            for j, s in enumerate(sol):
                sn = s.get("step_num")
                if not (isinstance(sn, int) and not isinstance(sn, bool) and sn > 0):
                    errs.append(f"examples[{i}].solution[{j}].step_num")
                if not (isinstance(s.get("operation"), str) and s["operation"]):
                    errs.append(f"examples[{i}].solution[{j}].operation")
                for opt in ("result", "description"):
                    if opt in s and not isinstance(s[opt], str):
                        errs.append(f"examples[{i}].solution[{j}].{opt}")
    for opt in ("key_reminders", "common_mistakes"):
        if opt in r and not (isinstance(r[opt], list) and all(isinstance(x, str) for x in r[opt])):
            errs.append(opt)
    v = r.get("version")
    if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
        errs.append("version")
    if "sourceDocumentId" in r and not isinstance(r["sourceDocumentId"], str):
        errs.append("sourceDocumentId")
    if r.get("generationMethod") not in (None, "template", "llm", "converted"):
        errs.append("generationMethod")
    return errs


def enrichment_score(rec: dict) -> tuple:
    """Dedup preference: real scaffold first, then richer enrichment, then key count."""
    vs = rec.get("visual_scaffold") or {}
    return (1 if vs.get("type") in SCAFFOLD_TYPES else 0,
            1 if rec.get("_validation_status") else 0,
            len(rec))


def adapt(rec: dict, overrides: dict | None = None) -> tuple[dict | None, dict]:
    """Returns (frontend_record | None, meta{trust, repairs, quarantine_reasons}).

    `overrides` maps template_id -> scaffold decision from the verification panel;
    it fills MISSING scaffolds only and never displaces one the source already has.
    """
    meta = {"repairs": [], "quarantine": []}
    src = rec.get("source") or {}
    concept = rec.get("concept") or {}

    technique = concept.get("technique_name")
    if not technique:
        technique = concept.get("sub_topic")
        if technique:
            meta["repairs"].append("technique_name_from_sub_topic")
        else:
            meta["quarantine"].append("no_technique_or_sub_topic")

    difficulty = rec.get("difficulty")
    if isinstance(difficulty, int) and difficulty > 5:
        meta["repairs"].append(f"difficulty_clamped_{difficulty}_to_5")
        difficulty = 5
    if not (isinstance(difficulty, int) and 1 <= difficulty <= 5):
        meta["quarantine"].append("difficulty_invalid")

    vs = rec.get("visual_scaffold") or {}
    override = (overrides or {}).get(rec.get("template_id")) if overrides else None
    scaffold_placeholder = False
    if vs.get("type") in SCAFFOLD_TYPES:
        scaffold = {"type": vs["type"]}
        if isinstance(vs.get("config"), dict):
            scaffold["config"] = vs["config"]
    elif override and override.get("scaffold_type") in SCAFFOLD_TYPES:
        # Enrichment decided by the adversarially-verified scaffold panel; provenance
        # travels with the record so a degraded-quorum choice stays auditable.
        scaffold = {"type": override["scaffold_type"]}
        cfg = dict(override.get("config") or {})
        cfg["scaffold_source"] = override.get("status", "panel")
        if not override.get("full_quorum", True):
            cfg["low_quorum"] = True
        scaffold["config"] = cfg
        meta["repairs"].append(f"scaffold_from_panel_{override.get('status', 'panel')}")
    else:
        scaffold = {"type": "textual_scaffold",
                    "config": {"placeholder": True, "needs_visual_enrichment": True}}
        scaffold_placeholder = True
        meta["repairs"].append("scaffold_placeholder_textual")

    examples, step_counts = [], []
    for e in rec.get("examples") or []:
        stmt = e.get("problem_statement")
        sol_in = e.get("solution") or []
        if not stmt:
            meta["quarantine"].append("empty_problem_statement")
            continue
        if not sol_in:
            meta["quarantine"].append("empty_solution")
            continue
        sol = []
        for s in sol_in:
            step = {"step_num": s.get("step_num"), "operation": s.get("operation")}
            if s.get("formula") is not None:
                step["result"] = str(s["formula"])
            if s.get("reasoning") is not None:
                step["description"] = str(s["reasoning"])
            sol.append(step)
        ex_out = {"problem_statement": stmt, "solution": sol}
        ans = e.get("final_answer", e.get("answer"))
        if ans is not None:
            ex_out["answer"] = str(ans)
        examples.append(ex_out)
        step_counts.append(len(sol))
    if not examples:
        meta["quarantine"].append("no_valid_examples")

    legacy_status = rec.get("_validation_status")
    if legacy_status == "flagged":
        meta["quarantine"].append("legacy_validation_flagged")

    if meta["quarantine"]:
        meta["trust"] = "quarantined"
        return None, meta

    out = {
        "id": rec["template_id"],
        "domain": BOOK_DOMAIN.get(src.get("book"), DEFAULT_DOMAIN),
        "concept": {"technique_name": technique, "category": concept.get("topic") or "General"},
        "difficulty": difficulty,
        "expected_time": synth_expected_time(difficulty, rec.get("cognitive_load_score") or 3, step_counts),
        "visual_scaffold": scaffold,
        "examples": examples,
        "version": 1,
        "sourceDocumentId": f"{src.get('book', 'unknown')}#p{src.get('page', '?')}",
        "generationMethod": "template",
    }
    if concept.get("sub_topic"):
        out["concept"]["sub_category"] = concept["sub_topic"]
    if rec.get("key_reminders"):
        out["key_reminders"] = [str(x) for x in rec["key_reminders"]]
    if rec.get("common_mistakes"):
        out["common_mistakes"] = [str(x) for x in rec["common_mistakes"]]

    verified = legacy_status in ("verified_L1", "verified_L2")
    if verified and not scaffold_placeholder and not meta["repairs"]:
        meta["trust"] = "trusted_candidate"
    else:
        meta["trust"] = "sandbox_candidate"
    return out, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", default="incoming/topic_browser_full_package/content_data/templates/solve_along")
    ap.add_argument("--out", default="data/factory/solvealong_bank_v1.jsonl")
    ap.add_argument("--manifest", default="data/factory/solvealong_bank_v1.manifest.json")
    ap.add_argument("--scaffold-overrides", default=None,
                    help="JSON {decisions:[{template_id, scaffold_type, config, status, full_quorum}]} "
                         "from the scaffold verification panel")
    args = ap.parse_args()

    overrides = {}
    if args.scaffold_overrides:
        payload = json.loads(Path(args.scaffold_overrides).read_text())
        for d in payload.get("decisions", payload if isinstance(payload, list) else []):
            overrides[d["template_id"]] = d
        print(f"scaffold overrides loaded: {len(overrides)}")

    by_id: dict[str, dict] = {}
    files = sorted(Path(args.input_dir).glob("*.jsonl"))
    total_records = 0
    for path in files:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            total_records += 1
            tid = rec["template_id"]
            if tid not in by_id or enrichment_score(rec) > enrichment_score(by_id[tid]):
                by_id[tid] = rec

    bank, trust_by_id, quarantined, repairs_log = [], {}, {}, {}
    for tid in sorted(by_id):
        out, meta = adapt(by_id[tid], overrides)
        if out is None:
            quarantined[tid] = meta["quarantine"]
            continue
        errs = validate_frontend_record(out)
        if errs:  # contract violation is a bug in this adapter, not in the data
            print(f"FATAL: adapted record {tid} violates frontend schema: {errs}", file=sys.stderr)
            return 1
        bank.append(out)
        trust_by_id[tid] = meta["trust"]
        if meta["repairs"]:
            repairs_log[tid] = meta["repairs"]

    out_path, man_path = Path(args.out), Path(args.manifest)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in bank:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    et = [r["expected_time"] for r in bank]
    manifest = {
        "bank": out_path.name,
        "generated_by": "factory/adapters/solvealong_adapter.py",
        "expected_time_version": EXPECTED_TIME_VERSION,
        "source_files": [p.name for p in files],
        "input_records": total_records,
        "unique_templates": len(by_id),
        "emitted": len(bank),
        "trust_entry_recommendation": dict(Counter(trust_by_id.values())),
        "quarantined_count": len(quarantined),
        "quarantined": quarantined,
        "repairs": repairs_log,
        "expected_time_stats": {"min": min(et), "median": statistics.median(et), "max": max(et)},
        "scaffold_overrides_applied": sum(
            1 for r in bank if (r["visual_scaffold"].get("config") or {}).get("scaffold_source")),
        "placeholder_scaffolds_remaining": sum(
            1 for r in bank if (r["visual_scaffold"].get("config") or {}).get("placeholder")),
        "trust_by_id": trust_by_id,
        "notes": [
            "Trust values are ladder ENTRY recommendations; promotion requires the 7-stage auditor.",
            "Legacy _python_audit_status ignored (broken pre-loss verifier, ALL_FAILED on 806/807).",
            "No cat_data content consumed: answers derive from the Phase-1 solve_along books only.",
        ],
    }
    man_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))

    print(f"emitted {len(bank)}/{len(by_id)} templates -> {out_path}")
    print(f"trust: {manifest['trust_entry_recommendation']}  quarantined: {len(quarantined)}")
    print(f"expected_time s: {manifest['expected_time_stats']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
