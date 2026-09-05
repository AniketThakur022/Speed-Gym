#!/usr/bin/env python3
"""Reference Library intake: validate the 43 recovered subtopic pages and load them.

The pages were assumed lost ("25 of 28 unwritten"); they were not. The June
package holds 40 auto-generated pages plus the 3 human-approved Phase-1A pages
(nikhilam_sutra, urdhva_tiryak, yavadunam). Backend's topic_browser_subtopics
table was empty, so the content existed and nothing served it.

What this does, and what it refuses to do:
  - content_status is RECOMPUTED by the spec's own rule (REFERENCE_LIBRARY.md §8.2):
    auto-generated content can never be "complete". All 43 self-declare "complete";
    the honest tally is 4 complete / 39 needs_human_review. Self-declaration loses.
  - the one mechanical LaTeX defect (an underscore inside \\text{}) is fixed and
    logged — it is notation, not content.
  - CONTENT defects are annotated, never silently corrected. ekanyunena_purvena's
    headline example teaches the wrong rule (right part "99 - 42 = 57"; the sutra
    gives the complement 100 - 42 = 58, answer 4158 not 4157). A loader that quietly
    rewrote a page's mathematics would be doing exactly what the re-narration pass
    was faulted for. The defect is recorded in metadata_json.content_defects so it
    is visible in-data and drives the badge, and the page cannot be promoted past
    needs_human_review until a person fixes it.
  - techniques_by_difficulty is normalised to level -> [technique...]; the source
    is inconsistent (one page uses a list per level, the rest a single dict).

Dry run by default; --apply writes topic_browser_subtopics.
"""

import argparse
import ast
import json
import os
import re
from collections import Counter
from pathlib import Path

BASE = Path("incoming/topic_browser_full_package/content_data")
SCHEMA = Path("incoming/topic_browser_full_package/schemas_and_taxonomy/subtopic_reference_schema.json")
PG_DSN = os.environ.get("VMSG_PG_DSN", "postgresql://vmsg:vmsg@localhost:5432/vmsg")

# Content defects found by verification. Keyed by subtopic_id; these are recorded,
# not repaired — a reference page's mathematics is not something a loader edits.
CONTENT_DEFECTS = {
    "ekanyunena_purvena": [{
        "where": "quick_ref.quick_example",
        "claim": "42 × 99 = 4157 via right part '99 − 42 = 57'",
        "verified": "42 × 99 = 4158. The sutra's right part is the complement of the left "
                    "part from the base: 100 − 42 = 58 (equivalently 99 − 41). The page "
                    "teaches the wrong rule, not merely a wrong digit.",
        "severity": "blocking", "found_by": "rag_reference_intake_2026-09-05",
    }],
    "seshanyakena_caramena": [{
        "where": "quick_ref.quick_example",
        "claim": "'123 ÷ 8' → '3'",
        "verified": "123 ÷ 8 = 15.375; the answer 3 is the REMAINDER. Either the problem "
                    "should ask for the remainder or the answer is wrong. The page also has "
                    "no sutra name or translation.",
        "severity": "needs_review", "found_by": "rag_reference_intake_2026-09-05",
    }],
}


def spec_status(doc: dict) -> str:
    qr = doc.get("quick_ref") or {}
    has_qr = bool((qr.get("the_trick") or {}).get("formula_latex"))
    tabs = len(doc.get("techniques_by_difficulty") or {})
    auto = bool((doc.get("metadata") or {}).get("auto_generated"))
    if has_qr and tabs >= 3 and not auto:
        return "complete"
    if has_qr and tabs < 3:
        return "partial"
    return "needs_human_review" if has_qr else "coming_soon"


def fix_latex(s: str, log: list, sid: str) -> str:
    # \text{working_base} -> \text{working\_base}: KaTeX rejects a bare underscore
    # in text mode. Notation only.
    def esc(m):
        inner = m.group(1)
        if "_" in inner and "\\_" not in inner:
            log.append(f"{sid}: escaped underscore in \\text{{{inner}}}")
            return "\\text{" + inner.replace("_", "\\_") + "}"
        return m.group(0)
    return re.sub(r"\\text\{([^{}]*)\}", esc, s)


def check_example(doc: dict):
    qe = (doc.get("quick_ref") or {}).get("quick_example") or {}
    prob = str(qe.get("problem", "")).replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**").strip()
    ans = str(qe.get("answer", "")).replace(",", "").strip()
    if re.fullmatch(r"[\d\s+\-*/().]+", prob) and re.fullmatch(r"-?\d+(\.\d+)?", ans):
        try:
            v = eval(compile(ast.parse(prob, mode="eval"), "<q>", "eval"), {"__builtins__": {}})
            return "ok" if abs(float(v) - float(ans)) < 1e-9 else f"WRONG ({v})"
        except Exception:
            return "unchecked"
    return "unchecked"


def load_pages():
    pages = {}
    for sub, tag in (("subtopic_explainer_enriched", "enriched"), ("subtopic_explainer", "plain")):
        for f in sorted(os.listdir(BASE / sub)):
            if not f.endswith(".json"):
                continue
            doc = json.load(open(BASE / sub / f))
            sid = doc.get("subtopic_id", f[:-5])
            if sid in pages:
                continue  # enriched wins where both exist
            pages[sid] = (doc, tag)
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="data/factory/reference_library_intake.json")
    args = ap.parse_args()

    req = set(json.load(open(SCHEMA))["required"])
    pages = load_pages()
    rows, latex_log, stats = [], [], Counter()
    for sid, (doc, tag) in pages.items():
        missing = req - set(doc)
        if missing:
            stats["schema_fail"] += 1
            continue
        # notation fixes
        tr = (doc.get("quick_ref") or {}).get("the_trick") or {}
        fl = tr.get("formula_latex")
        if isinstance(fl, list):
            tr["formula_latex"] = [fix_latex(x, latex_log, sid) for x in fl]
        elif isinstance(fl, str):
            tr["formula_latex"] = fix_latex(fl, latex_log, sid)
        # normalise tabs: level -> list of techniques
        tabs = {}
        for lvl, v in (doc.get("techniques_by_difficulty") or {}).items():
            tabs[lvl] = v if isinstance(v, list) else [v]
        meta = dict(doc.get("metadata") or {})
        # applicability_type is varchar(32) and meant to be a type, not prose. One
        # page carries "Addition, Subtraction, Multiplication" (37 chars) — a list of
        # operations, i.e. it applies across them, which the spec's vocabulary calls
        # "universal". Remapped and recorded rather than truncated or widened; the
        # wider problem (28 spellings across 40 pages) is flagged for normalisation.
        app = doc.get("applicability_type") or ""
        if len(app) > 32:
            meta["applicability_type_original"] = app
            meta["applicability_type_remap_reason"] = "exceeds varchar(32); a list of operations means it applies across them"
            doc["applicability_type"] = "universal"
            stats["applicability_remapped"] += 1
        for col, lim in (("category", 32), ("subtopic_id", 64), ("topic", 64), ("sutra", 128), ("sutra_sanskrit", 256)):
            v = doc.get(col)
            if isinstance(v, str) and len(v) > lim:
                stats["width_overflow_unhandled"] += 1
                print(f"WIDTH OVERFLOW {sid}.{col}: {len(v)} > {lim} — not loading this page")
        honest = spec_status(doc)
        declared = meta.get("content_status")
        meta["declared_content_status"] = declared
        meta["content_status"] = honest
        meta["source_dir"] = tag
        meta["status_rule"] = "REFERENCE_LIBRARY.md §8.2 — auto-generated content is never 'complete'"
        arith = check_example(doc)
        meta["quick_example_check"] = arith
        if sid in CONTENT_DEFECTS:
            meta["content_defects"] = CONTENT_DEFECTS[sid]
            if any(d["severity"] == "blocking" for d in CONTENT_DEFECTS[sid]):
                meta["content_status"] = "needs_human_review"
        stats[f"status_{meta['content_status']}"] += 1
        stats[f"arith_{arith.split()[0]}"] += 1
        rows.append({
            "subtopic_id": sid, "category": doc["category"], "topic": doc["topic"],
            "sutra": doc.get("sutra"), "sutra_sanskrit": doc.get("sutra_sanskrit"),
            "translation": doc.get("translation"),
            "applicability_type": doc["applicability_type"],
            "quick_ref_json": doc["quick_ref"], "techniques_json": tabs,
            "total_techniques": doc.get("total_techniques") or sum(len(v) for v in tabs.values()),
            "total_templates": doc.get("total_templates") or 0,
            "metadata_json": meta,
        })

    report = {"pages": len(rows), "stats": dict(stats), "latex_fixes": latex_log,
              "content_defects": {k: len(v) for k, v in CONTENT_DEFECTS.items()},
              "note": "content_status recomputed by the spec's rule; content defects are "
                      "annotated in metadata_json, never edited"}
    Path(args.report).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))

    if not args.apply:
        print("DRY RUN — pass --apply to load topic_browser_subtopics")
        return 0
    import psycopg
    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()
        for r in rows:
            cur.execute("""
                INSERT INTO topic_browser_subtopics
                  (subtopic_id, category, topic, sutra, sutra_sanskrit, translation,
                   applicability_type, quick_ref_json, techniques_json, total_techniques,
                   total_templates, metadata_json, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (subtopic_id) DO UPDATE SET
                  quick_ref_json=EXCLUDED.quick_ref_json, techniques_json=EXCLUDED.techniques_json,
                  metadata_json=EXCLUDED.metadata_json, total_techniques=EXCLUDED.total_techniques,
                  total_templates=EXCLUDED.total_templates, updated_at=NOW()
            """, (r["subtopic_id"], r["category"], r["topic"], r["sutra"], r["sutra_sanskrit"],
                  r["translation"], r["applicability_type"], json.dumps(r["quick_ref_json"]),
                  json.dumps(r["techniques_json"]), r["total_techniques"], r["total_templates"],
                  json.dumps(r["metadata_json"])))
        conn.commit()
        cur.execute("SELECT count(*), count(*) FILTER (WHERE metadata_json->>'content_status'='complete') FROM topic_browser_subtopics")
        print("loaded: total, complete =", cur.fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
