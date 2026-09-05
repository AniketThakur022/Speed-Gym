#!/usr/bin/env python3
"""Join SolveAlong templates (bank + generator patterns) to Reference Library pages.

The pages carry `techniques_by_difficulty.template_count` but no template ids, so
the topic_browser_subtopic_templates junction cannot be filled from the pages.
It has to come from the factory side: which bank/generated content teaches the
sub-topic a page explains.

Why this is an ALIAS TABLE and not string similarity: the first attempt was a
token-overlap join, and it filed the bank's 41 "Ekadhikena Purvena" (one MORE
than the previous — squaring numbers ending in 5, 1/19 decimals) templates under
the `ekanyunena_purvena` page (one LESS than the previous — the x99 rule) because
the two share "purvena" and "previous". A learner opening the x99 page would be
handed 41 walkthroughs of a different sutra. Two Vedic sutras that differ by one
prefix syllable are exactly the case a fuzzy join cannot be trusted with, so every
mapping here is explicit, and everything not explicitly mapped is DECLINED with a
reason and listed — never guessed.

Three confidence classes:
  exact      the bank sub_category IS the page's sub-topic (sutra name or the same
             named topic). Loaded.
  topic      the page is a foundation-level page for the whole topic (e.g. bank
             "Triangles" -> page geometry_basics). A real relation, but the page's
             difficulty tabs name specific techniques, so this is reported as a
             CANDIDATE for a human to approve, not loaded by default.
  declined   no page exists (Ekadhikena, Dhvajanka, Paravartya, all of Calculus and
             Statistics), or the bucket needs a per-template split ("Basic Operations"
             spans four pages), or it is not mathematics at all.

Ties: `yavadunam` (Phase-1A, human-approved, in the plain directory) and
`yavadunam_tavadunam` (auto-generated) describe the same sutra. The human-approved
page wins; the duplicate is recorded so the library can retire it.

Dry run by default; --apply writes the junction and sets each page's
total_templates to the count actually joined (the declared value was a count with
no ids behind it).
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from factory.generation import t2

BANK = Path("data/factory/solvealong_bank_v1_4.jsonl")
PG_DSN = os.environ.get("VMSG_PG_DSN", "postgresql://vmsg:vmsg@localhost:5432/vmsg")

# bank `concept.sub_category` -> (subtopic_id, confidence)
EXACT = {
    "Nikhilam Navatashcaramam (All from 9, Last from 10)": "nikhilam_sutra",
    "Urdhva Tiryagbhyam (Vertically and Crosswise)": "urdhva_tiryak",
    "Yavadunam Sutra (Deficiency/Surplus Squaring)": "yavadunam",
    "Yavadunam (Whatever the Extent of its Deficiency)": "yavadunam",
    "Shunyam Saamyasamuccaye (When Samuccaya is Same, It is Zero)": "shunyam_saamyasamuccaye",
    "Linear Equations": "linear_equations",
    "Quadratic Equations": "quadratic_equations",
    "Polynomials and Factoring": "polynomials",
    "Complex Numbers": "complex_numbers",
    "Complex Numbers (Polar Form Operations)": "complex_numbers",
    "Functions and Graphs": "functions_graphs",
    "Fractions and Decimals": "fractions",
    "Ratios and Proportions": "ratios_proportions",
    "Percentages": "percentages",
    "Mensuration (Area/Volume)": "mensuration",
    "Calendar Calculations": "calendar_calculations",
    "Magic Squares Construction": "magic_squares",
    "Magic Squares (Properties and Construction)": "magic_squares",
}
EXACT_PREFIX = {"Magic Squares — ": "magic_squares"}   # six order/variant sub-categories

TOPIC = {   # foundation page for the whole topic — candidates only
    "Coordinate Geometry": "geometry_basics", "Triangles": "geometry_basics",
    "Circles": "geometry_basics", "Quadrilaterals": "geometry_basics",
    "Conic Sections (Parabola, Ellipse, Hyperbola)": "geometry_basics",
    "Trigonometric Ratios": "trigonometry_basics", "Trigonometric Equations": "trigonometry_basics",
    "Trigonometric Identities": "trigonometry_basics", "Heights and Distances": "trigonometry_basics",
    "Inverse Trigonometric Functions": "trigonometry_basics", "Trigonometric Functions": "trigonometry_basics",
    "Number Bases": "number_theory", "Modular Arithmetic": "number_theory",
    "Divisibility Rules": "number_theory", "HCF and LCM (Advanced)": "number_theory",
    "Decimal Expansions of Fractions": "number_theory", "Pythagorean Triples Generation": "number_theory",
    "Axiomatic Foundations of Integers": "number_theory",
    "Exponents and Radicals": "order_of_operations",
}

DECLINE = {
    "Ekadhikena Purvena (One More than the Previous)":
        "NO PAGE. Not ekanyunena_purvena — a different sutra (one MORE vs one LESS than the previous).",
    "Dhvajanka Sutra (Flag Division)": "NO PAGE for flag division; division_tricks is generic and unverified for it.",
    "Dhvajāṅka Sūtra (Flag Digit Division)": "NO PAGE (see Dhvajanka).",
    "Paravartya Yojayet (Transpose and Apply)": "NO PAGE.",
    "Basic Operations (+, -, ×, ÷)":
        "spans addition/subtraction/multiplication/division_tricks; needs a per-template operation split, not a bucket join.",
    "None": "bank template has no sub_category.",
    "Dissociation and Double Dissociation in Neuropsychology": "not mathematics — flag for bank hygiene.",
}
DECLINE_TOPICS = {"Calculus": "NO PAGE for any Calculus sub-topic.",
                  "Statistics": "NO PAGE for any Statistics sub-topic."}

# generator pattern id -> page (or None with reason)
GENERATOR = {   # keys are t2.PATTERNS ids, verified against the module, not guessed
    "mult_near_base": ("nikhilam_sutra", None),
    "nikhilam_complement": ("nikhilam_sutra", None),
    "square_near_base": ("yavadunam", None),
    "urdhva_2x2": ("urdhva_tiryak", None),
    "mult_by_11": (None, "NO PAGE; multiplication_tricks is generic and unverified for the x11 neighbour-sum rule."),
    "ekadhikena_square_5": (None, "NO PAGE (same gap as the bank's 41 Ekadhikena templates)."),
}
DUPLICATE_PAGES = {"yavadunam_tavadunam": "duplicate of the human-approved `yavadunam` page (same sutra); retire or merge."}


def classify(category: str, sub: str):
    if sub in EXACT:
        return EXACT[sub], "exact", None
    for pfx, sid in EXACT_PREFIX.items():
        if sub.startswith(pfx):
            return sid, "exact", None
    if sub in DECLINE:
        return None, "declined", DECLINE[sub]
    if sub in TOPIC:
        return TOPIC[sub], "topic", None
    if category in DECLINE_TOPICS:
        return None, "declined", DECLINE_TOPICS[category]
    return None, "declined", "no explicit mapping (unmapped sub_category) — add to the alias table or leave unserved."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="data/factory/reference_page_join.json")
    args = ap.parse_args()

    joins, candidates, declined = [], [], []
    for line in BANK.read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        cat = t["concept"].get("category") or ""
        sub = t["concept"].get("sub_category") or t["concept"].get("technique_name") or "None"
        sid, conf, why = classify(cat, str(sub))
        # bank difficulty is 1..5; the pages' tabs are keyed L1..L5, and the junction's
        # difficulty_level is varchar(8) NOT NULL — "L3" is the shared vocabulary.
        lvl = t.get("difficulty")
        row = {"template_id": t["id"], "source": "bank_v1_4", "sub_category": sub, "category": cat,
               "difficulty_level": f"L{lvl}" if lvl in (1, 2, 3, 4, 5) else None,
               "technique_id": (t["concept"].get("technique_name") or "")[:128] or None}
        if conf == "exact":
            joins.append({**row, "subtopic_id": sid, "confidence": "exact"})
        elif conf == "topic":
            candidates.append({**row, "subtopic_id": sid, "confidence": "topic"})
        else:
            declined.append({**row, "reason": why})

    gen_rows, gen_declined = [], []
    for pid in t2.PATTERNS:
        sid, why = GENERATOR.get(pid, (None, "generator pattern not in the alias table"))
        (gen_rows if sid else gen_declined).append(
            {"pattern_id": pid, "subtopic_id": sid, "source": "t2_pattern", "confidence": "exact"} if sid
            else {"pattern_id": pid, "reason": why})

    per_page = Counter(j["subtopic_id"] for j in joins)
    report = {
        "bank_templates": len(joins) + len(candidates) + len(declined),
        "joined_exact": len(joins), "candidates_topic_level": len(candidates), "declined": len(declined),
        "pages_served": len(per_page), "per_page": dict(per_page.most_common()),
        "generator_patterns_joined": gen_rows, "generator_patterns_declined": gen_declined,
        "declined_by_reason": dict(Counter(d["reason"] for d in declined).most_common()),
        "candidates_by_page": dict(Counter(c["subtopic_id"] for c in candidates).most_common()),
        "duplicate_pages": DUPLICATE_PAGES,
        "method": "explicit alias table; unmapped sub-categories are declined, never guessed "
                  "(a token-overlap join misfiled 41 Ekadhikena templates under ekanyunena_purvena)",
        "joins": joins, "candidates": candidates, "declined": declined,
    }
    Path(args.report).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k not in ("joins", "candidates", "declined")}, indent=1, ensure_ascii=False))

    if not args.apply:
        print("DRY RUN — pass --apply to write topic_browser_subtopic_templates")
        return 0
    import psycopg
    with psycopg.connect(PG_DSN) as conn:
        cur = conn.cursor()
        # The junction has no unique key on (subtopic_id, template_id) and no column for
        # confidence, so: only `exact` rows are written, the source tag identifies this
        # load, and a re-run replaces its own rows rather than stacking duplicates.
        skipped = [j for j in joins if not j["difficulty_level"]]
        cur.execute("DELETE FROM topic_browser_subtopic_templates WHERE source = 'bank_v1_4'")
        for j in joins:
            if not j["difficulty_level"]:
                continue
            cur.execute("""INSERT INTO topic_browser_subtopic_templates
                             (subtopic_id, difficulty_level, template_id, technique_id, source)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (j["subtopic_id"], j["difficulty_level"], j["template_id"], j["technique_id"], j["source"]))
        loaded_per_page = Counter(j["subtopic_id"] for j in joins if j["difficulty_level"])
        for sid, n in loaded_per_page.items():
            cur.execute("UPDATE topic_browser_subtopics SET total_templates=%s, updated_at=NOW() WHERE subtopic_id=%s", (n, sid))
        conn.commit()
        cur.execute("SELECT count(*), count(DISTINCT subtopic_id) FROM topic_browser_subtopic_templates WHERE source='bank_v1_4'")
        print("junction rows, pages =", cur.fetchone(), "| skipped for missing difficulty:", len(skipped))
        cur.execute("""SELECT subtopic_id, difficulty_level, count(*) FROM topic_browser_subtopic_templates
                       WHERE subtopic_id IN ('nikhilam_sutra','yavadunam') GROUP BY 1,2 ORDER BY 1,2""")
        print("per-tab check:", cur.fetchall())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
